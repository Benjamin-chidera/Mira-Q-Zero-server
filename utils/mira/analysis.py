import os
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select
from database import engine
from models import (
    Patient, Allergy, Medication, PatientDocument, 
    ClinicalNotes, OperativeNote, PACSImaging,
    MedicalGuidelineCache, PatientNotification
)
from utils.mira.ai_research_models import ResearchConversation, ResearchMessage

# Initialize Tavily search tool
try:
    from langchain_community.tools import TavilySearchResults
    tavily = TavilySearchResults(max_results=2)
except Exception as e:
    print(f"[Analysis Tool] Could not import Tavily: {e}")
    tavily = None

# Initialize ChatNVIDIA LLM
try:
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    llm = ChatNVIDIA(
        model="meta/llama-3.3-70b-instruct",
        nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
        temperature=0.1
    )
except Exception as e:
    print(f"[Analysis Tool] Could not import ChatNVIDIA: {e}")
    llm = None

async def broadcast_notification(payload: Dict[str, Any]):
    """Emit the notification live over socket setup."""
    try:
        from socket_setup import sio
        await sio.emit("notification:new", payload)
        print(f"[Socket.IO Alert] Emitted notification:new for patient {payload.get('patient_id')}")
    except Exception as e:
        print(f"[Socket.IO Alert] Socket emission failed: {e}")

def get_or_fetch_guideline(keyword: str, session: Session) -> str:
    """Check MedicalGuidelineCache for keyword; fetch via Tavily if missing."""
    keyword_clean = keyword.strip().lower()
    if not keyword_clean:
        return ""
        
    cached = session.exec(
        select(MedicalGuidelineCache).where(MedicalGuidelineCache.keyword == keyword_clean)
    ).first()
    
    if cached:
        print(f"[Guideline Cache] Cache HIT for: {keyword_clean}")
        return cached.guidelines_json
        
    print(f"[Guideline Cache] Cache MISS for: {keyword_clean}. Fetching via Tavily...")
    guidelines_text = ""
    if tavily:
        try:
            # Perform targeted query
            search_query = f"{keyword_clean} clinical guidelines contraindications drug interactions warnings BNF NHS"
            search_results = tavily.invoke(search_query)
            guidelines_text = str(search_results)
        except Exception as e:
            print(f"[Guideline Cache] Tavily search error: {e}")
            guidelines_text = f"Failed to retrieve guidelines for {keyword_clean} online."
    else:
        guidelines_text = f"Tavily search is unavailable. Presumed guideline search for: {keyword_clean}."

    # Cache guidelines
    new_cache = MedicalGuidelineCache(
        keyword=keyword_clean,
        guidelines_json=guidelines_text
    )
    session.add(new_cache)
    session.commit()
    session.refresh(new_cache)
    return guidelines_text

def get_patient_profile_context(patient_id: int, session: Session) -> dict:
    """
    Fetches the patient's record, builds a comprehensive clinical profile context string,
    and returns it along with raw active medications and allergies records.
    """
    patient = session.get(Patient, patient_id)
    if not patient:
        return {"profile_text": "", "medications": [], "allergies": []}

    # 2. Fetch Active Medications
    medications = session.exec(
        select(Medication)
        .where(Medication.patient_id == patient_id)
        .where(Medication.status == "Active")
    ).all()

    # 3. Fetch Active Allergies
    allergies = session.exec(
        select(Allergy)
        .where(Allergy.patient_id == patient_id)
        .where(Allergy.status == "Active")
    ).all()

    # 4. Fetch Patient Documents
    documents = session.exec(
        select(PatientDocument)
        .where(PatientDocument.patient_id == patient_id)
    ).all()

    # 5. Fetch Clinical Notes
    clinical_notes = session.exec(
        select(ClinicalNotes)
        .where(ClinicalNotes.patient_id == patient_id)
    ).all()

    # 6. Fetch Operative Notes
    operative_notes = session.exec(
        select(OperativeNote)
        .where(OperativeNote.patient_id == patient_id)
    ).all()

    # 7. Fetch PACS Imaging Reports
    pacs_imaging = session.exec(
        select(PACSImaging)
        .where(PACSImaging.patient_id == patient_id)
    ).all()

    patient_profile = f"""
PATIENT ID: {patient.id}
NAME: {patient.name}
AGE: {patient.age}
GENDER: {patient.gender}
NHS NUMBER: {patient.nhs_number}

ACTIVE MEDICATIONS:
{', '.join([f"{m.drug_name} ({m.dosage} - {m.frequency})" for m in medications]) if medications else 'None'}

ACTIVE ALLERGIES:
{', '.join([f"{a.substance} (Criticality: {a.criticality}, Reaction: {a.reaction})" for a in allergies]) if allergies else 'None'}

PATIENT DOCUMENTS / DISCHARGE SUMMARIES:
{chr(10).join([f"- {d.title}: {d.content}" for d in documents]) if documents else 'None'}

CLINICAL NOTES:
{chr(10).join([f"- {n.content} (Author: {n.author})" for n in clinical_notes]) if clinical_notes else 'None'}

OPERATIVE NOTES:
{chr(10).join([f"- {o.procedure_name}: performed {o.procedure_performed}. Narrative: {o.narrative_text}" for o in operative_notes]) if operative_notes else 'None'}

PACS IMAGING REPORTS:
{chr(10).join([f"- Accession {p.accession_number} ({p.modality} of {p.body_site}): {p.radiologist_report}" for p in pacs_imaging]) if pacs_imaging else 'None'}
"""
    return {
        "profile_text": patient_profile.strip(),
        "medications": medications,
        "allergies": allergies,
        "patient": patient
    }

def analyze_patient_sync(patient_id: int):
    """
    Synchronous orchestrator for analyzing patient clinical records.
    Called inside fastapi.background_tasks to prevent blocking API requests.
    """
    with Session(engine) as session:
        # Fetch Patient and context using helper
        ctx = get_patient_profile_context(patient_id, session)
        patient = ctx["patient"]
        if not patient:
            print(f"[Analysis] Patient #{patient_id} not found.")
            return

        medications = ctx["medications"]
        allergies = ctx["allergies"]
        patient_profile = ctx["profile_text"]

        # Gather keywords for caching
        keywords = []
        for med in medications:
            keywords.append(med.drug_name)
        for alg in allergies:
            keywords.append(alg.substance)

        # Retrieve guidelines from cache/Tavily
        guidelines_list = []
        for kw in set(keywords):
            g_text = get_or_fetch_guideline(kw, session)
            if g_text:
                guidelines_list.append(f"=== Guidelines for {kw} ===\n{g_text}")

        guidelines_context = "\n\n".join(guidelines_list)

        if not llm:
            print("[Analysis] Llama/ChatNVIDIA LLM not loaded. Aborting analysis.")
            return

        prompt = f"""
You are an expert clinical safety agent. You are tasked with analyzing a patient's clinical profile and comparing it against provided drug, allergy, and clinical guidelines to ensure safety.

[PATIENT CLINICAL PROFILE]
{patient_profile}

[CLINICAL GUIDELINES & CONTRAINDICATIONS CONTEXT]
{guidelines_context}

Evaluate the profile for:
1. Drug-Allergy Interactions (e.g. prescribed Penicillin when patient is allergic to Penicillin or related compounds).
2. Drug-Disease/Contraindications (e.g. prescribed Metformin when clinical reports/scans indicate renal failure or low kidney clearance).
3. Drug-Drug Interactions (e.g. combination of two medications that causes severe side effects or clinical failures).
4. Treatment inconsistencies (e.g. notes say patient is being prepared for surgery but active medications conflict, or procedures logged are inconsistent with narrative notes).

Provide your response strictly in the following JSON format:
{{
  "has_alert": true/false,
  "alerts": [
    {{
      "title": "Alert Title describing the issue",
      "message": "Specific details on why this is an issue and reference guidelines/notes that support this concern.",
      "severity": "High" or "Medium" or "Low"
    }}
  ]
}}
Ensure your output is strictly valid JSON and nothing else.
"""
        
        try:
            response = llm.invoke(prompt)
            result_json = response.content.strip()
            
            # Extract JSON if returned with markdown wrappers
            if result_json.startswith("```json"):
                result_json = result_json.split("```json")[1].split("```")[0].strip()
            elif result_json.startswith("```"):
                result_json = result_json.split("```")[1].split("```")[0].strip()
                
            analysis_result = json.loads(result_json)
        except Exception as err:
            print(f"[Analysis] Parsing LLM analysis response failed: {err}. Raw: {response.content if 'response' in locals() else ''}")
            return

        # 9. Handle alerts
        if analysis_result.get("has_alert") and analysis_result.get("alerts"):
            for alert in analysis_result["alerts"]:
                title = alert.get("title", "Clinical Alert")
                message = alert.get("message", "A potential clinical conflict was identified.")
                severity = alert.get("severity", "Medium")

                # Check if this alert has already been logged to avoid duplication
                existing = session.exec(
                    select(PatientNotification)
                    .where(PatientNotification.patient_id == patient_id)
                    .where(PatientNotification.title == title)
                ).first()
                if existing:
                    print(f"[Analysis] Alert '{title}' already exists. Skipping.")
                    continue

                # Create ResearchConversation for interactive followup
                conv_id = f"alert_conv_{datetime.utcnow().timestamp()}"
                conversation = ResearchConversation(
                    id=conv_id,
                    practitioner_id=patient.doctor_id or 1,
                    title=f"Alert: {title[:30]}",
                    preview=message[:90] + "...",
                    conversation_type="chat",
                    status="Ongoing"
                )
                session.add(conversation)
                session.commit()

                # Add initial messages
                system_message = ResearchMessage(
                    id=f"msg_s_alert_{datetime.utcnow().timestamp()}",
                    conversation_id=conv_id,
                    role="system",
                    content=(
                        f"You are Mira, a clinical AI assistant.\n"
                        f"This conversation was generated because of a clinical alert:\n"
                        f"**{title}**\n\n"
                        f"{message}\n\n"
                        f"Discuss with the practitioner and check literature or alternative treatments to resolve this issue safely."
                    )
                )
                session.add(system_message)

                # Add PatientNotification linked to the conversation
                notification = PatientNotification(
                    patient_id=patient_id,
                    title=title,
                    message=message,
                    severity=severity,
                    status="Unresolved",
                    conversation_id=conv_id
                )
                session.add(notification)
                session.commit()
                session.refresh(notification)

                # Emit Socket notification
                payload = {
                    "patient_id": patient_id,
                    "notification_id": notification.id,
                    "title": title,
                    "message": message,
                    "severity": severity,
                    "conversation_id": conv_id,
                    "created_at": notification.created_at.isoformat()
                }
                asyncio.run(broadcast_notification(payload))

def invalidate_patient_summary(patient_id: int):
    """
    Deletes the patient summary cache so that the next request reconstructs it.
    """
    from models import PatientSummaryCache
    with Session(engine) as session:
        existing = session.get(PatientSummaryCache, patient_id)
        if existing:
            session.delete(existing)
            session.commit()
            print(f"[Summary Cache] Invalidated summary cache for patient {patient_id}")

def trigger_patient_analysis(patient_id: int):
    """Entry point to analyze patient records asynchronously."""
    # Synchronously invalidate summary cache immediately
    try:
        invalidate_patient_summary(patient_id)
    except Exception as e:
        print(f"[Summary Cache] Synchronous invalidation failed: {e}")

    # Run in a background thread to prevent API thread starvation
    asyncio.get_event_loop().run_in_executor(
        None,
        analyze_patient_sync,
        patient_id
    )
