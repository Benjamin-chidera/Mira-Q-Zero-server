from sqlmodel import SQLModel, Field, Session, select, Column
from sqlalchemy import TEXT
from datetime import datetime
from typing import Optional
import json

class CaseHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    practitioner_id: int = Field(index=True)
    conversation_id: str = Field(index=True)
    title: str
    preview: str
    status: str  # "Completed", "Failed", "Abandoned", "Deleted"
    status_reason: Optional[str] = Field(default=None)
    messages_json: str = Field(sa_column=Column(TEXT, nullable=False))  # JSON serialized list of conversation messages
    updated_at: datetime = Field(default_factory=datetime.utcnow)

def log_case_history(
    session: Session,
    practitioner_id: int,
    conversation_id: str,
    title: str,
    preview: str,
    status: str,
    status_reason: Optional[str],
    messages: list
) -> CaseHistory:
    """
    Logs or updates a case history record in the database.
    """
    # Check if a history record already exists for this conversation
    stmt = select(CaseHistory).where(CaseHistory.conversation_id == conversation_id)
    existing = session.exec(stmt).first()

    messages_serialized = json.dumps(messages)

    if existing:
        existing.status = status
        existing.status_reason = status_reason
        existing.messages_json = messages_serialized
        existing.preview = preview
        existing.title = title
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    else:
        new_history = CaseHistory(
            practitioner_id=practitioner_id,
            conversation_id=conversation_id,
            title=title,
            preview=preview,
            status=status,
            status_reason=status_reason,
            messages_json=messages_serialized
        )
        session.add(new_history)
        session.commit()
        session.refresh(new_history)
        return new_history
