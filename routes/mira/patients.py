import httpx
import uuid
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/medTech/patients", tags=["patients"])

# Instead of searching by practice, get a single patient by their NHS Number
PDS_SINGLE_PATIENT_URL = "https://sandbox.api.service.nhs.uk/personal-demographics/FHIR/R4/Patient"



request_id = str(uuid.uuid4())
headers = {
    "Accept": "application/fhir+json",
    "X-Request-ID": request_id,
}   

from database import get_session
from models import Patient, Booking, User
from sqlmodel import select
from fastapi import Depends
from sqlmodel import Session

@router.get("/")
async def get_practice_patients(
    ods_code: str = "B82617",
    doctor_id: int | None = None,
    session: Session = Depends(get_session)
):
    # In dev, we don't 'search' PDS. We fetch our known patients.
    patients = []
    
    # 1. Fetch from local Database
    if doctor_id is not None:
        db_patients = session.exec(select(Patient).where(Patient.doctor_id == doctor_id)).all()
    else:
        db_patients = session.exec(select(Patient)).all()
        
    seen_nhs_numbers = set()
    for p in db_patients:
        # Find bookings for this patient by matching on patient_name
        patient_bookings = session.exec(
            select(Booking).where(Booking.patient_name == p.name)
        ).all()

        # Resolve doctor name
        doctor_name = "Not assigned"
        if p.doctor_id:
            doctor = session.get(User, p.doctor_id)
            if doctor:
                doctor_name = doctor.name

        patients.append({
            "id": p.id,
            "nhsNumber": p.nhs_number,
            "name": p.name,
            "age": p.age,
            "gender": p.gender,
            "dateOfBirth": p.date_of_birth,
            "status": "Review",
            "reason": patient_bookings[0].symptoms if patient_bookings else "Not set yet",
            "doctorName": doctor_name
        })
        seen_nhs_numbers.add(p.nhs_number)
        
    return {"patients": patients}


@router.patch("/{patient_id}")
async def update_patient_details(
    patient_id: int,
    data: dict,
    session: Session = Depends(get_session),
):
    """
    Update patient details like name, nhs_number, gender, date_of_birth, age.
    """
    patient = session.exec(select(Patient).where(Patient.id == patient_id)).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if "name" in data:
        patient.name = data["name"]
    if "nhs_number" in data:
        patient.nhs_number = data["nhs_number"]
    if "gender" in data:
        patient.gender = data["gender"]
    if "date_of_birth" in data:
        patient.date_of_birth = data["date_of_birth"]
    if "age" in data:
        try:
            patient.age = int(data["age"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Age must be an integer")

    session.commit()
    session.refresh(patient)

    # Invalidate cache
    try:
        from utils.mira.analysis import invalidate_patient_summary
        invalidate_patient_summary(patient_id)
    except Exception as e:
        print(f"[Summary Cache] Invalidation failed: {e}")

    return {
        "message": "Patient details updated successfully",
        "patient": {
            "id": patient.id,
            "nhsNumber": patient.nhs_number,
            "name": patient.name,
            "age": patient.age,
            "gender": patient.gender,
            "dateOfBirth": patient.date_of_birth,
        }
    }


@router.get("/{patient_id}/summary")
def get_patient_summary(
    patient_id: int,
    session: Session = Depends(get_session)
):
    import json
    from models import PatientSummaryCache
    from utils.mira.analysis import get_patient_profile_context, llm

    # Check database cache first
    cached = session.get(PatientSummaryCache, patient_id)
    if cached:
        try:
            print(f"[Summary Cache] Cache HIT for patient {patient_id}")
            bullets = json.loads(cached.summary_json)
            return {"summary": bullets}
        except Exception as e:
            print(f"[Summary Cache] Failed to load cache: {e}. Re-generating...")

    print(f"[Summary Cache] Cache MISS for patient {patient_id}. Querying LLM...")

    ctx = get_patient_profile_context(patient_id, session)
    patient = ctx.get("patient")
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
        
    profile_text = ctx.get("profile_text", "")
    if not profile_text:
        return {"summary": ["No clinical data available to summarize."]}
        
    if not llm:
        return {"summary": ["AI Summarization service is currently offline.", f"Patient Name: {patient.name}"]}

    prompt = f"""
You are an expert clinical AI assistant. Summarize everything known about this patient in 2 to 4 concise, high-impact clinical bullet points.
Highlight active concerns, trends, critical allergies, active medications, and post-op/surgical statuses.
Keep each bullet point to 1-2 clear, professional sentences. Do not use generic placeholders.

[PATIENT CLINICAL PROFILE]
{profile_text}

Provide your response strictly in the following JSON format:
{{
  "summary": [
    "Bullet point 1 detailing key clinical status, medication, or allergy concern.",
    "Bullet point 2 detailing recent procedures or diagnostic findings.",
    "Bullet point 3 detailing current treatment plan status."
  ]
}}
Ensure your output is strictly valid JSON and nothing else.
"""
    try:
        response = llm.invoke(prompt)
        result_json = response.content.strip()
        if result_json.startswith("```json"):
            result_json = result_json.split("```json")[1].split("```")[0].strip()
        elif result_json.startswith("```"):
            result_json = result_json.split("```")[1].split("```")[0].strip()
            
        data = json.loads(result_json)
        bullets = data.get("summary", [])

        # Save to database cache
        if bullets:
            try:
                new_cache = PatientSummaryCache(
                    patient_id=patient_id,
                    summary_json=json.dumps(bullets)
                )
                session.merge(new_cache)
                session.commit()
                print(f"[Summary Cache] Saved new summary cache for patient {patient_id}")
            except Exception as cache_err:
                print(f"[Summary Cache] Failed to save cache: {cache_err}")

        return {"summary": bullets}
    except Exception as e:
        print(f"[Summary Endpoint] Error: {e}")
        return {"summary": ["Failed to generate dynamic AI summary.", f"Error: {str(e)}"]}


@router.post("/{patient_id}/ask-mira")
def ask_mira(
    patient_id: int,
    payload: dict,
    session: Session = Depends(get_session)
):
    from utils.mira.analysis import get_patient_profile_context, llm

    question = payload.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="Missing required field: question")

    ctx = get_patient_profile_context(patient_id, session)
    patient = ctx.get("patient")
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
        
    profile_text = ctx.get("profile_text", "")
    if not llm:
        raise HTTPException(status_code=503, detail="AI service is currently offline.")

    prompt = f"""
You are Mira, a clinical AI assistant. You are answering a question from a practitioner about this patient.
Answer the question accurately, professionally, and concisely using the provided patient clinical profile.
If the profile does not contain the answer, state that it is not in the patient's records.

[PATIENT CLINICAL PROFILE]
{profile_text}

Practitioner Question: {question}

Provide your answer in clear, markdown-friendly text. Keep it clinical and brief.
"""
    try:
        response = llm.invoke(prompt)
        return {"answer": response.content.strip()}
    except Exception as e:
        print(f"[Ask Mira Endpoint] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query AI service: {str(e)}")