from fastapi import APIRouter, HTTPException, Depends
from starlette import status
from sqlmodel import Session, select
from database import get_session
from models import OperativeNote, Patient
from datetime import datetime

router = APIRouter(prefix="/mira/operative_notes", tags=["mira-operative-notes"])

"""
Surgical Treatments: Stored in the operative_notes table.
This details invasive procedures, physical anatomical corrections, and step-by-step surgical workflows.

Like PACS imaging, operative notes are NEVER deleted or modified directly.
"""


# Create a new operative note
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_operative_note(
    note: OperativeNote,
    session: Session = Depends(get_session),
):
    """
    Create a new operative note.
    Surgical treatments are append-only and cannot be updated or deleted.
    """
    # Verify the patient exists before creating an operative note
    patient = session.exec(
        select(Patient).where(Patient.id == note.patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Set creation timestamp and save record
    note.created_at = datetime.utcnow()
    session.add(note)
    session.commit()
    session.refresh(note)

    return {
        "message": "Operative note created successfully",
        "note_id": note.id,
    }


# Get all operative notes for a patient
@router.get("/{patient_id}")
async def get_patient_operative_notes(
    patient_id: int,
    session: Session = Depends(get_session),
):
    """
    Get all operative notes for a patient, ordered by surgery date/creation date descending.
    """
    # Verify patient exists
    patient = session.exec(
        select(Patient).where(Patient.id == patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Query notes for this patient, ordered by newest first
    notes = session.exec(
        select(OperativeNote)
        .where(OperativeNote.patient_id == patient_id)
        .order_by(OperativeNote.created_at.desc())
    ).all()

    return notes


# Get a single operative note by ID
@router.get("/{patient_id}/{note_id}")
async def get_operative_note(
    patient_id: int,
    note_id: int,
    session: Session = Depends(get_session),
):
    """
    Get a single operative note by its ID.
    """
    # Find the note matching patient_id and note_id
    note = session.exec(
        select(OperativeNote).where(
            OperativeNote.patient_id == patient_id,
            OperativeNote.id == note_id,
        )
    ).first()

    if not note:
        raise HTTPException(status_code=404, detail="Operative note not found")

    return note