from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from database import get_session
from utils.mira.ai_research_models import ResearchConversation
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/mira/research", tags=["mira-research-center"])

class StatusUpdate(BaseModel):
    status: str  # "Completed", "Failed", "Abandoned"
    reason: Optional[str] = None

@router.patch("/conversations/{conversation_id}/status")
def update_conversation_status(
    conversation_id: str,
    payload: StatusUpdate,
    session: Session = Depends(get_session)
):
    """Updates the status and reason of a research conversation."""
    conv = session.get(ResearchConversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    valid_statuses = ["Completed", "Failed", "Abandoned", "Ongoing"]
    if payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of {valid_statuses}")
        
    conv.status = payload.status
    conv.status_reason = payload.reason
    session.add(conv)
    session.commit()
    session.refresh(conv)
    
    # Log to Case History
    if payload.status in ["Completed", "Failed", "Abandoned"]:
        from utils.mira.case_history.history import log_case_history
        from utils.mira.ai_research_models import ResearchMessage
        import json
        
        stmt = select(ResearchMessage).where(ResearchMessage.conversation_id == conversation_id).order_by(ResearchMessage.created_at.asc())
        msgs = session.exec(stmt).all()
        messages_list = []
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
            messages_list.append({
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.created_at.strftime("%H:%M"),
                "attachments": attachments,
                "sources": sources
            })
            
        log_case_history(
            session=session,
            practitioner_id=conv.practitioner_id,
            conversation_id=conversation_id,
            title=conv.title,
            preview=conv.preview,
            status=payload.status,
            status_reason=payload.reason,
            messages=messages_list
        )
    
    # Audit log print
    print(f"[Audit] Conversation '{conversation_id}' status updated to '{payload.status}'. Reason: '{payload.reason}'")
    
    return {
        "message": "Status updated successfully",
        "conversation_id": conversation_id,
        "status": conv.status,
        "status_reason": conv.status_reason
    }
