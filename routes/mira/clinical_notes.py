from fastapi import APIRouter, HTTPException, Depends
from starlette import status
from sqlmodel import Session, select
from database import get_session
from models import ClinicalNotes, Patient
from datetime import datetime

router = APIRouter(prefix="/mira/clinical_notes", tags=["mira-clinical-notes"])

"""
Medical/Non-Surgical Treatments: Stored in the clinicalnotes table.
This logs daily ward rounds, treatment modifications, therapy adjustments, and non-surgical care paths.

Like PACS imaging and operative notes, clinical notes are NEVER deleted or modified directly.
"""


# Create a new clinical note
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_clinical_note(
    note: ClinicalNotes,
    session: Session = Depends(get_session),
):
    """
    Create a new clinical/progress note for a patient.
    Clinical notes are append-only and cannot be updated or deleted.
    """
    # Verify the patient exists before creating a clinical note
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
        "message": "Clinical note created successfully",
        "note_id": note.id,
    }


# Get all clinical notes for a patient
@router.get("/{patient_id}")
async def get_patient_clinical_notes(
    patient_id: int,
    session: Session = Depends(get_session),
):
    """
    Get all clinical notes for a patient, ordered by creation date descending.
    """
    # Verify patient exists
    patient = session.exec(
        select(Patient).where(Patient.id == patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Query notes for this patient, ordered by newest first
    notes = session.exec(
        select(ClinicalNotes)
        .where(ClinicalNotes.patient_id == patient_id)
        .order_by(ClinicalNotes.created_at.desc())
    ).all()

    return notes


# Get a single clinical note by ID
@router.get("/{patient_id}/{note_id}")
async def get_clinical_note(
    patient_id: int,
    note_id: int,
    session: Session = Depends(get_session),
):
    """
    Get a single clinical note by its ID.
    """
    # Find the note matching patient_id and note_id
    note = session.exec(
        select(ClinicalNotes).where(
            ClinicalNotes.patient_id == patient_id,
            ClinicalNotes.id == note_id,
        )
    ).first()

    if not note:
        raise HTTPException(status_code=404, detail="Clinical note not found")

    return note