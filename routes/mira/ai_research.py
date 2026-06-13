import json
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from database import get_session
from utils.mira.ai_research_models import ResearchConversation, ResearchMessage

router = APIRouter(prefix="/mira/research", tags=["mira-research"])

@router.get("/conversations")
def get_conversations(practitioner_id: int, session: Session = Depends(get_session)):
    """Fetches all research conversations for a given practitioner."""
    stmt = select(ResearchConversation).where(
        ResearchConversation.practitioner_id == practitioner_id
    ).order_by(ResearchConversation.updated_at.desc())
    convs = session.exec(stmt).all()
    
    return [
        {
            "id": conv.id,
            "title": conv.title,
            "preview": conv.preview,
            "date": conv.created_at.strftime("%b %d"),
            "timestamp": conv.created_at.strftime("%H:%M"),
            "type": conv.conversation_type
        }
        for conv in convs
    ]

@router.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str, session: Session = Depends(get_session)):
    """Fetches all messages for a specific conversation in chronological order."""
    stmt = select(ResearchMessage).where(
        ResearchMessage.conversation_id == conversation_id
    ).order_by(ResearchMessage.created_at.asc())
    msgs = session.exec(stmt).all()
    
    result = []
    for msg in msgs:
        attachments = []
        if msg.attachments_json:
            try:
                attachments = json.loads(msg.attachments_json)
            except Exception:
                pass
                
        sources = []
        if msg.sources_json:
            try:
                sources = json.loads(msg.sources_json)
            except Exception:
                pass
                
        result.append({
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "timestamp": msg.created_at.strftime("%H:%M"),
            "attachments": attachments,
            "sources": sources
        })
        
    return result

@router.post("/conversations")
def create_conversation(data: dict, session: Session = Depends(get_session)):
    """Creates a new research conversation session."""
    conv_id = data.get("id")
    practitioner_id = data.get("practitioner_id")
    title = data.get("title", "New Research Session")
    conv_type = data.get("type", "chat")
    
    if not conv_id or not practitioner_id:
        raise HTTPException(status_code=400, detail="Missing required fields: id, practitioner_id")
        
    existing = session.get(ResearchConversation, conv_id)
    if existing:
        return {"message": "Conversation already exists", "conversation_id": conv_id}
        
    conv = ResearchConversation(
        id=conv_id,
        practitioner_id=practitioner_id,
        title=title,
        preview="No messages yet",
        conversation_type=conv_type
    )
    session.add(conv)
    session.commit()
    
    return {"message": "Conversation created", "conversation_id": conv_id}

@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, session: Session = Depends(get_session)):
    """Deletes a conversation and all its associated messages."""
    conv = session.get(ResearchConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    # Delete associated messages
    stmt = select(ResearchMessage).where(ResearchMessage.conversation_id == conversation_id)
    msgs = session.exec(stmt).all()
    for msg in msgs:
        session.delete(msg)
        
    session.delete(conv)
    session.commit()
    
    return {"message": "Conversation deleted successfully"}
