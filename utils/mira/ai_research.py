import os
import io
import re
import base64
import json
import sqlite3
import urllib.request
from typing import TypedDict, Annotated, List, Dict, Any, Union
from datetime import datetime
from bs4 import BeautifulSoup
from pypdf import PdfReader

from sqlmodel import Session, select
from database import engine

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from utils.mira.crew_config import get_mira_crew, thread_local_sources
from utils.mira.ai_research_models import ResearchConversation, ResearchMessage
from utils.redis_client import redis_client
import hashlib

from dotenv import load_dotenv
load_dotenv()

def get_cache_key(query: str, attachments: list) -> str:
    # Sort keys for consistent serialization
    attachments_str = json.dumps(attachments or [], sort_keys=True)
    combined = f"query:{query}|attachments:{attachments_str}"
    return "mira:research_cache:" + hashlib.md5(combined.encode("utf-8")).hexdigest()

# Set NVIDIA_NIM_API_KEY for CrewAI/litellm compatibility if not already set
if os.getenv("NVIDIA_API_KEY") and not os.getenv("NVIDIA_NIM_API_KEY"):
    os.environ["NVIDIA_NIM_API_KEY"] = os.getenv("NVIDIA_API_KEY")

# ─── State Definition ─────────────────────────────────────────────────────────

class ResearchState(TypedDict):
    conversation_id: str
    practitioner_id: int
    user_query: str
    attachments: List[Dict[str, Any]]
    extracted_context: str
    chat_history: List[Dict[str, str]]
    intent: str
    response: str
    sources: List[Dict[str, str]]

# ─── Input Processing Helpers ─────────────────────────────────────────────────

def extract_text_from_pdf(base64_data: str) -> str:
    """Extracts text content from a base64 encoded PDF file."""
    try:
        pdf_bytes = base64.b64decode(base64_data)
        pdf_file = io.BytesIO(pdf_bytes)
        reader = PdfReader(pdf_file)
        text = ""
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text += f"\n--- Page {i+1} ---\n{page_text}"
        return text.strip()
    except Exception as e:
        print(f"[AI Researcher] PDF extraction error: {e}")
        return f"[Error extracting text from PDF: {str(e)}]"

def analyze_image_with_nvidia(base64_data: str) -> str:
    """Uses NVIDIA Llama 3.2 Vision to transcribe and describe medical images."""
    try:
        # Check if model exists or fallback.
        # ChatNVIDIA accepts list format user content containing text and image_url dicts.
        vision_llm = ChatNVIDIA(
            model="meta/llama-3.2-90b-vision-instruct",
            nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
            temperature=0.1
        )
        
        # Prepare content payloads
        content = [
            {"type": "text", "text": "You are a clinical AI assistant. Carefully transcribe all text, lab values, tables, and describe the clinical features seen in this image/scan."},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_data}"
                }
            }
        ]
        
        response = vision_llm.invoke([{"role": "user", "content": content}])
        return response.content
    except Exception as e:
        print(f"[AI Researcher] Vision error: {e}")
        # Try fallback model
        try:
            fallback_llm = ChatNVIDIA(
                model="meta/llama-3.2-11b-vision-instruct",
                nvidia_api_key=os.getenv("NVIDIA_API_KEY")
            )
            response = fallback_llm.invoke([{"role": "user", "content": content}])
            return response.content
        except Exception as e2:
            print(f"[AI Researcher] Vision fallback error: {e2}")
            return f"[Error analyzing image with vision model: {str(e)}]"

def scrape_url_content(url: str) -> str:
    """Scrapes raw text from a web URL using urllib and BeautifulSoup."""
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read()
        soup = BeautifulSoup(html, "html.parser")
        
        # Strip script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
            
        text = soup.get_text(separator=" ")
        # Clean whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk)
        return f"\n--- Content Scraped from {url} ---\n{text[:15000]}" # Limit to 15k chars
    except Exception as e:
        print(f"[AI Researcher] URL scraping error: {e}")
        return f"[Error scraping URL {url}: {str(e)}]"

# ─── LangGraph Nodes ──────────────────────────────────────────────────────────

def ingest_attachments(state: ResearchState) -> Dict[str, Any]:
    """Processes PDF, Image, and URL attachments, extracting readable text."""
    extracted = []
    attachments = state.get("attachments") or []
    
    for att in attachments:
        att_type = att.get("type")
        att_name = att.get("name", "attachment")
        base64_data = att.get("data")
        url = att.get("url")
        
        extracted.append(f"\n=== Attached {att_type.upper()}: {att_name} ===")
        
        if att_type == "pdf" and base64_data:
            pdf_text = extract_text_from_pdf(base64_data)
            extracted.append(pdf_text)
            
        elif att_type == "image" and base64_data:
            image_desc = analyze_image_with_nvidia(base64_data)
            extracted.append(image_desc)
            
        elif att_type == "url" and url:
            url_text = scrape_url_content(url)
            extracted.append(url_text)
            
    return {
        "extracted_context": "\n".join(extracted)
    }

def route_intent(state: ResearchState) -> Dict[str, Any]:
    """Classifies user intent: simple (direct_answer) or complex (deep_research)."""
    try:
        llm = ChatNVIDIA(
            model="meta/llama-3.3-70b-instruct",
            nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
            temperature=0,
            timeout=60
        )
        
        prompt = (
            "You are a clinical router. Classify the user query into either 'direct_answer' or 'deep_research'.\n"
            "Use 'direct_answer' for general Q&A, simple formatting requests, definitions, or queries that do not require clinical guidelines searching.\n"
            "Use 'deep_research' for looking up specific patient records/files, complex patient cases, guideline reviews (NICE, ESC, etc.), drug interaction reviews, or when multiple source integrations are required.\n\n"
            f"Query: {state['user_query']}\n"
            f"Has attachments: {len(state.get('attachments') or []) > 0}\n\n"
            "Respond with strictly 'direct_answer' or 'deep_research' and nothing else."
        )
        
        response = llm.invoke(prompt)
        intent = response.content.strip().lower()
        if "deep_research" in intent:
            result = "deep_research"
        else:
            result = "direct_answer"
    except Exception as e:
        print(f"[AI Researcher] Routing error: {e}")
        result = "deep_research"  # Fallback to safer, deeper research
        
    return {"intent": result}

def extract_sources_from_text(text: str) -> List[Dict[str, str]]:
    """Extracts markdown links from the text and formats them as source objects."""
    matches = re.findall(r'\[([^\]]+)\]\(((?:https?://(?:[^()]+|\([^()]*\))+))\)', text)
    sources = []
    seen_urls = set()
    for idx, (label, url) in enumerate(matches):
        url = url.strip()
        if url not in seen_urls:
            seen_urls.add(url)
            source_type = "url"
            if url.lower().endswith(".pdf"):
                source_type = "pdf"
            sources.append({
                "id": f"ref_{idx}_{int(datetime.utcnow().timestamp())}",
                "label": label.strip(),
                "url": url,
                "type": source_type
            })
    return sources

def direct_answer(state: ResearchState) -> Dict[str, Any]:
    """Handles simple QA queries quickly with a single LLM call and Tavily web search."""
    from langchain_community.tools import TavilySearchResults
    tavily = TavilySearchResults(max_results=3)
    
    search_context = ""
    search_sources = []
    try:
        search_results = tavily.invoke(state["user_query"])
        search_context = f"\n=== Web Search Results ===\n{str(search_results)}\n"
        
        # Parse search results to collect verified sources
        if isinstance(search_results, list):
            for idx, r in enumerate(search_results):
                if isinstance(r, dict) and "url" in r:
                    search_sources.append({
                        "id": f"qa_search_{idx}_{int(datetime.utcnow().timestamp())}",
                        "label": r.get("title") or "Web Search Result",
                        "url": r["url"],
                        "type": "url"
                    })
    except Exception as e:
        print(f"[AI Researcher] Quick Q&A search error: {e}")

    llm = ChatNVIDIA(
        model="meta/llama-3.3-70b-instruct",
        nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
        temperature=0.3,
        timeout=60
    )
    
    # Format chat history
    history_str = ""
    for msg in state.get("chat_history") or []:
        history_str += f"{msg['role'].capitalize()}: {msg['content']}\n"
        
    prompt = (
        "You are Mira, a helpful and highly accurate clinical AI assistant.\n"
        "Provide a direct, medically sound response based on the patient case, query, history, and provided search context.\n\n"
        f"Chat History:\n{history_str}\n"
        f"Extracted Context from files/URLs:\n{state['extracted_context']}\n\n"
        f"Web Search Context:\n{search_context}\n\n"
        f"User Query: {state['user_query']}\n\n"
        "Provide your recommendation structured with bold headings. "
        "You MUST base your response on the provided 'Web Search Context' and 'Extracted Context' (files/images/URLs) rather than relying on your own memory or trained weights. "
        "When referencing search findings, please include standard clickable markdown links using the EXACT URLs from the 'Web Search Context' or 'Extracted Context'. "
        "🔴 CRITICAL: Never include markdown hyperlinks or URLs unless they are explicitly present in the provided 'Web Search Context' or 'Extracted Context'. Do not invent or hallucinate any URLs or links."
    )
    
    response = llm.invoke(prompt)
    response_text = response.content
    
    # Extract cited sources from the generated text
    cited_sources = extract_sources_from_text(response_text)
    
    # Merge and deduplicate cited sources and search results
    sources = []
    seen_urls = set()
    for src in cited_sources:
        if src.get("url") not in seen_urls:
            seen_urls.add(src["url"])
            sources.append(src)
            
    for src in search_sources:
        if src.get("url") not in seen_urls:
            seen_urls.add(src["url"])
            sources.append(src)
            
    if not sources:
        sources = [{"label": "Direct LLM Answer", "type": "protocol"}]
        
    return {
        "response": response_text,
        "sources": sources
    }

def crew_research(state: ResearchState) -> Dict[str, Any]:
    """Triggers CrewAI multi-agent clinical research for complex questions."""
    # Initialize thread-local storage for accumulated sources
    thread_local_sources.sources = []
    
    crew = get_mira_crew()
    
    # Run CrewAI synchronously
    inputs = {
        "user_query": state["user_query"],
        "extracted_context": state["extracted_context"]
    }
    
    result = crew.kickoff(inputs=inputs)
    response_text = str(result)
    
    # 1. Start with the sources accumulated by the search tools during execution
    accumulated = getattr(thread_local_sources, "sources", [])
    
    # 2. Extract sources directly mentioned in the final markdown output (clickable markdown links)
    markdown_sources = extract_sources_from_text(response_text)
    
    # Merge them by URL to ensure uniqueness
    sources = []
    seen_urls = set()
    
    # Prioritize markdown sources as they are explicitly cited in the text
    for src in markdown_sources:
        if src["url"] not in seen_urls:
            seen_urls.add(src["url"])
            sources.append(src)
            
    # Then add any other unique search results
    for idx, src in enumerate(accumulated):
        if src["url"] not in seen_urls:
            seen_urls.add(src["url"])
            src["id"] = f"search_{idx}_{int(datetime.utcnow().timestamp())}"
            sources.append(src)
            
    # If no sources found at all, we can fallback to standard citations
    if not sources:
        sources.append({
            "id": f"s_fallback_{int(datetime.utcnow().timestamp())}",
            "label": "Tavily Search Engine",
            "type": "url",
            "url": "https://tavily.com"
        })
        
    return {
        "response": response_text,
        "sources": sources
    }

# ─── Graph Construction ───────────────────────────────────────────────────────

def decide_routing(state: ResearchState) -> str:
    """Helper path decider for LangGraph conditional edges."""
    return state["intent"]

# Connect to database for LangGraph checkpointers
conn = sqlite3.connect("./gp_connect.db", check_same_thread=False)

# Build Graph
builder = StateGraph(ResearchState)
builder.add_node("ingest_attachments", ingest_attachments)
builder.add_node("route_intent", route_intent)
builder.add_node("direct_answer", direct_answer)
builder.add_node("crew_research", crew_research)

builder.add_edge(START, "ingest_attachments")
builder.add_edge("ingest_attachments", "route_intent")
builder.add_conditional_edges(
    "route_intent",
    decide_routing,
    {
        "direct_answer": "direct_answer",
        "deep_research": "crew_research"
    }
)
builder.add_edge("direct_answer", END)
builder.add_edge("crew_research", END)

# Compile with persistent SQLite saver
memory_saver = SqliteSaver(conn)
mira_research_graph = builder.compile(checkpointer=memory_saver)

# ─── DB & Invocation Integrations ─────────────────────────────────────────────

def run_mira_research(
    conversation_id: str,
    practitioner_id: int,
    query: str,
    attachments: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Executes the research graph, loading history from the database,
    and saving the conversation/messages back to gp_connect.db.
    """
    attachments = attachments or []
    
    is_transient = conversation_id.startswith("transient_")
    
    with Session(engine) as session:
        # 1. Ensure Conversation exists
        conv = session.get(ResearchConversation, conversation_id)
        if not conv:
            conv = ResearchConversation(
                id=conversation_id,
                practitioner_id=practitioner_id,
                title=query[:50] or "New Research Session",
                preview="Starting lookup...",
                conversation_type="chat"
            )
            session.add(conv)
            session.commit()
            session.refresh(conv)

            # Seed transient patient details context if conversation ID starts with transient_patient_
            if conversation_id.startswith("transient_patient_"):
                try:
                    parts = conversation_id.split("_")
                    patient_id = int(parts[2])
                    from models import Patient, Medication, Allergy, PatientDocument, ClinicalNotes, OperativeNote, PACSImaging
                    patient = session.get(Patient, patient_id)
                    if patient:
                        meds = session.exec(select(Medication).where(Medication.patient_id == patient_id).where(Medication.status == "Active")).all()
                        allergies = session.exec(select(Allergy).where(Allergy.patient_id == patient_id).where(Allergy.status == "Active")).all()
                        docs = session.exec(select(PatientDocument).where(PatientDocument.patient_id == patient_id)).all()
                        notes = session.exec(select(ClinicalNotes).where(ClinicalNotes.patient_id == patient_id)).all()
                        op_notes = session.exec(select(OperativeNote).where(OperativeNote.patient_id == patient_id)).all()
                        pacs = session.exec(select(PACSImaging).where(PACSImaging.patient_id == patient_id)).all()

                        meds_str = ", ".join([f"{m.drug_name} ({m.dosage} - {m.frequency})" for m in meds]) if meds else "None"
                        allergies_str = ", ".join([f"{a.substance} (Reaction: {a.reaction})" for a in allergies]) if allergies else "None"
                        docs_str = "\n".join([f"- {d.title}: {d.content}" for d in docs]) if docs else "None"
                        notes_str = "\n".join([f"- {n.content} (Author: {n.author})" for n in notes]) if notes else "None"
                        op_notes_str = "\n".join([f"- {o.procedure_name}: {o.procedure_performed}. Narrative: {o.narrative_text}" for o in op_notes]) if op_notes else "None"
                        pacs_str = "\n".join([f"- Accession {p.accession_number} ({p.modality}): {p.radiologist_report}" for p in pacs]) if pacs else "None"

                        context = (
                            f"You are Mira, a helpful and highly accurate clinical AI assistant.\n"
                            f"You are discussing NHS Patient: {patient.name} (Age: {patient.age}, Gender: {patient.gender}, NHS: {patient.nhs_number}) with their GP.\n"
                            f"Here is the patient's complete file context loaded from GP-Connect:\n"
                            f"Active Medications: {meds_str}\n"
                            f"Active Allergies: {allergies_str}\n"
                            f"Documents / Discharge Summaries:\n{docs_str}\n"
                            f"Clinical Notes:\n{notes_str}\n"
                            f"Operative Notes:\n{op_notes_str}\n"
                            f"PACS Imaging Reports:\n{pacs_str}\n\n"
                            f"Structure your recommendations with bold headings. Assist the doctor in reviewing or auditing this patient's records."
                        )

                        sys_msg = ResearchMessage(
                            id=f"msg_sys_context_{datetime.utcnow().timestamp()}",
                            conversation_id=conversation_id,
                            role="system",
                            content=context,
                            attachments_json="[]"
                        )
                        session.add(sys_msg)
                        session.commit()
                except Exception as ex:
                    print(f"[AI Researcher] Error seeding transient patient context: {ex}")
            
        # 2. Fetch Chat History
        stmt = select(ResearchMessage).where(
            ResearchMessage.conversation_id == conversation_id
        ).order_by(ResearchMessage.created_at)
        db_messages = session.exec(stmt).all()
        
        chat_history = []
        for msg in db_messages:
            chat_history.append({
                "role": msg.role,
                "content": msg.content
            })
            
        # Check cache
        cache_key = get_cache_key(query, attachments)
        cached_result = None
        if redis_client:
            try:
                val = redis_client.get(cache_key)
                if val:
                    cached_result = json.loads(val)
                    print(f"[Redis Cache] Cache hit for query: '{query[:30]}'")
            except Exception as e:
                print(f"[Redis Cache] Error reading cache: {e}")

        if cached_result:
            response_val = cached_result["response"]
            sources_val = cached_result["sources"]
        else:
            # 3. Assemble Initial LangGraph State
            initial_state = {
                "conversation_id": conversation_id,
                "practitioner_id": practitioner_id,
                "user_query": query,
                "attachments": attachments,
                "extracted_context": "",
                "chat_history": chat_history,
                "intent": "",
                "response": "",
                "sources": []
            }
            
            # 4. Invoke LangGraph
            config = {"configurable": {"thread_id": conversation_id}}
            final_state = mira_research_graph.invoke(initial_state, config=config)
            response_val = final_state["response"]
            sources_val = final_state["sources"]
            
            # Cache the new result
            if redis_client:
                try:
                    redis_client.setex(
                        cache_key,
                        3600,
                        json.dumps({
                            "response": response_val,
                            "sources": sources_val
                        })
                    )
                    print(f"[Redis Cache] Cached result for key: {cache_key}")
                except Exception as e:
                    print(f"[Redis Cache] Error writing to cache: {e}")

        # 5. Save User Message
        user_message = ResearchMessage(
            id=f"msg_u_{datetime.utcnow().timestamp()}",
            conversation_id=conversation_id,
            role="user",
            content=query,
            attachments_json=json.dumps(attachments)
        )
        session.add(user_message)
        
        # 6. Save Agent Response
        agent_message = ResearchMessage(
            id=f"msg_a_{datetime.utcnow().timestamp()}",
            conversation_id=conversation_id,
            role="agent",
            content=response_val,
            sources_json=json.dumps(sources_val)
        )
        session.add(agent_message)
        
        # 7. Update Conversation Preview (only if not transient)
        if not is_transient and conv:
            conv.preview = response_val[:100] + "..."
            conv.updated_at = datetime.utcnow()
            session.add(conv)
        
        session.commit()
        
        return {
            "response": response_val,
            "sources": sources_val
        }
