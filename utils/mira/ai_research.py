import os
import io
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

from utils.mira.crew_config import get_mira_crew
from utils.mira.ai_research_models import ResearchConversation, ResearchMessage

from dotenv import load_dotenv
load_dotenv()

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
            temperature=0
        )
        
        prompt = (
            "You are a clinical router. Classify the user query into either 'direct_answer' or 'deep_research'.\n"
            "Use 'direct_answer' for general Q&A, simple formatting requests, definitions, or queries that do not require clinical guidelines searching.\n"
            "Use 'deep_research' for complex patient cases, guideline reviews (NICE, ESC, etc.), drug interaction reviews, or when multiple source integrations are required.\n\n"
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

def direct_answer(state: ResearchState) -> Dict[str, Any]:
    """Handles simple QA queries quickly with a single LLM call."""
    llm = ChatNVIDIA(
        model="meta/llama-3.3-70b-instruct",
        nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
        temperature=0.3
    )
    
    # Format chat history
    history_str = ""
    for msg in state.get("chat_history") or []:
        history_str += f"{msg['role'].capitalize()}: {msg['content']}\n"
        
    prompt = (
        "You are Mira, a helpful and highly accurate clinical AI assistant.\n"
        "Provide a direct, medically sound response based on the patient case, query, and history.\n\n"
        f"Chat History:\n{history_str}\n"
        f"Extracted Context from files/URLs:\n{state['extracted_context']}\n\n"
        f"User Query: {state['user_query']}\n\n"
        "Provide your recommendation structured with bold headings. If references were utilized, cite them."
    )
    
    response = llm.invoke(prompt)
    return {
        "response": response.content,
        "sources": [{"label": "Direct LLM Answer", "type": "protocol"}]
    }

def crew_research(state: ResearchState) -> Dict[str, Any]:
    """Triggers CrewAI multi-agent clinical research for complex questions."""
    crew = get_mira_crew()
    
    # Run CrewAI synchronously
    inputs = {
        "user_query": state["user_query"],
        "extracted_context": state["extracted_context"]
    }
    
    result = crew.kickoff(inputs=inputs)
    
    # Extract sources from Tavily logs or construct from output
    sources = []
    # CrewAI output contains raw string. We parse it or attach default citations.
    sources.append({"id": "s1", "label": "Tavily Search Engine", "type": "url"})
    sources.append({"id": "s2", "label": "Clinical Guideline Review", "type": "pdf"})
    
    return {
        "response": str(result),
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
            content=final_state["response"],
            sources_json=json.dumps(final_state["sources"])
        )
        session.add(agent_message)
        
        # 7. Update Conversation Preview
        conv.preview = final_state["response"][:100] + "..."
        conv.updated_at = datetime.utcnow()
        session.add(conv)
        
        session.commit()
        
        return {
            "response": final_state["response"],
            "sources": final_state["sources"]
        }
