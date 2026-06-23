from sqlmodel import SQLModel, Field, Column
from sqlalchemy import TEXT
from datetime import datetime
from typing import Optional
import models

class ResearchConversation(SQLModel, table=True):
    id: str = Field(primary_key=True)
    practitioner_id: int = Field(foreign_key="user.id", index=True)
    title: str
    preview: str
    conversation_type: str = Field(default="chat")  # "chat" or "call"
    status: str = Field(default="Ongoing")          # "Ongoing", "Completed", "Failed", "Abandoned"
    status_reason: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ResearchMessage(SQLModel, table=True):
    id: str = Field(primary_key=True)
    conversation_id: str = Field(foreign_key="researchconversation.id", index=True, ondelete="CASCADE")
    role: str  # "user" or "agent"
    content: str = Field(sa_column=Column(TEXT, nullable=False))
    attachments_json: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))  # Serialized list of attachments
    sources_json: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))      # Serialized list of sources
    created_at: datetime = Field(default_factory=datetime.utcnow)
