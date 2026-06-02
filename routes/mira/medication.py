from fastapi import APIRouter, HTTPException, Depends
from starlette import status
from sqlmodel import Session, select
from database import get_session
from models import Medication, Patient
from datetime import datetime

router = APIRouter(prefix="/mira/medication", tags=["mira-medication"])

"""
Pharmaceutical Treatments: Stored in the medication table.
This acts as the legal record of drug doses, delivery routes, and administration times.

Medications cannot be deleted. Only the status (e.g. Active, Stopped, Completed) 
can be modified.
"""


# Create a new medication record
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_medication(
    medication: Medication,
    session: Session = Depends(get_session),
):
    """
    Create a new medication record for a patient.
    By default, status is set to 'Active'.
    """
    # Verify the patient exists before adding a medication
    patient = session.exec(
        select(Patient).where(Patient.id == medication.patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Set creation timestamp and save
    medication.created_at = datetime.utcnow()
    session.add(medication)
    session.commit()
    session.refresh(medication)

    return {
        "message": "Medication record created successfully",
        "medication_id": medication.id,
    }


# Get all medications for a patient
@router.get("/{patient_id}")
async def get_patient_medications(
    patient_id: int,
    session: Session = Depends(get_session),
):
    """
    Get all medications for a patient, ordered by creation date descending.
    """
    # Verify patient exists
    patient = session.exec(
        select(Patient).where(Patient.id == patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Query medications, newest first
    medications = session.exec(
        select(Medication)
        .where(Medication.patient_id == patient_id)
        .order_by(Medication.created_at.desc())
    ).all()

    return medications


# Get a single medication by ID
@router.get("/{patient_id}/{medication_id}")
async def get_medication(
    patient_id: int,
    medication_id: int,
    session: Session = Depends(get_session),
):
    """
    Get a single medication record by its ID.
    """
    medication = session.exec(
        select(Medication).where(
            Medication.patient_id == patient_id,
            Medication.id == medication_id,
        )
    ).first()

    if not medication:
        raise HTTPException(status_code=404, detail="Medication record not found")

    return medication


# Update the status of a medication
@router.patch("/{patient_id}/{medication_id}/status")
async def update_medication_status(
    patient_id: int,
    medication_id: int,
    update_data: dict,  # Expecting: {"status": "Stopped", "status_reason": "...", "updated_by": "..."}
    session: Session = Depends(get_session),
):
    """
    Update the status of a medication record.
    Medications cannot be deleted, but status can be changed (e.g., Active, Stopped, Completed).
    """
    # Find the medication matching patient_id and medication_id
    medication = session.exec(
        select(Medication).where(
            Medication.patient_id == patient_id,
            Medication.id == medication_id,
        )
    ).first()

    if not medication:
        raise HTTPException(status_code=404, detail="Medication record not found")

    # Validate that status is provided in request body
    new_status = update_data.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="status is required")

    # Update only the allowed status fields
    medication.status = new_status
    
    # Optional fields
    if "status_reason" in update_data:
        medication.status_reason = update_data["status_reason"]
    if "updated_by" in update_data:
        medication.updated_by = update_data["updated_by"]

    session.commit()
    session.refresh(medication)

    return {
        "message": "Medication status updated successfully",
        "medication_id": medication.id,
        "new_status": medication.status,
    }