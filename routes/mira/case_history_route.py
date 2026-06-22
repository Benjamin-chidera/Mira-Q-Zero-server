import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_session
from utils.mira.case_history.history import CaseHistory

router = APIRouter(prefix="/mira/case-history", tags=["mira-case-history"])

@router.get("")
def get_case_history(
    practitioner_id: int,
    status: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """
    Retrieves case history items for a specific practitioner.
    Supports filtering by status (success/completed, failure/failed, abandoned, deleted).
    """
    stmt = select(CaseHistory).where(CaseHistory.practitioner_id == practitioner_id).order_by(CaseHistory.updated_at.desc())
    items = session.exec(stmt).all()

    result = []
    for item in items:
        # Map statuses cleanly for client consumption
        client_status = "success" if item.status == "Completed" else item.status.lower()
        
        # If status filter is active, check match
        if status and status != "all" and client_status != status.lower():
            continue

        result.append({
            "id": item.conversation_id,
            "title": item.title,
            "preview": item.preview,
            "status": client_status,
            "status_reason": item.status_reason,
            "date": item.updated_at.strftime("%b %d"),
            "timestamp": item.updated_at.strftime("%H:%M")
        })

    return result

@router.get("/{conversation_id}/details")
def get_case_history_details(
    conversation_id: str,
    session: Session = Depends(get_session)
):
    """
    Retrieves full details (including serialized messages) for a specific case history item.
    """
    stmt = select(CaseHistory).where(CaseHistory.conversation_id == conversation_id)
    item = session.exec(stmt).first()
    if not item:
        raise HTTPException(status_code=404, detail="Case history item not found")

    messages = []
    if item.messages_json:
        try:
            messages = json.loads(item.messages_json)
        except Exception:
            pass

    return {
        "id": item.conversation_id,
        "title": item.title,
        "preview": item.preview,
        "status": "success" if item.status == "Completed" else item.status.lower(),
        "status_reason": item.status_reason,
        "date": item.updated_at.strftime("%b %d"),
        "messages": messages
    }
