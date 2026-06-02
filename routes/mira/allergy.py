from fastapi import APIRouter, HTTPException, Depends
from starlette import status
from sqlmodel import Session, select
from database import get_session
from models import Allergy, Patient
from datetime import datetime

router = APIRouter(prefix="/mira/allergy", tags=["mira-allergy"])

"""
Allergies: Stored in the allergy table.
Allergens can include medications, foods, latex, or environmental triggers.

Allergies can never be truly deleted or overwritten.
However, their status can be recorded as "Active" or "Inactive".
"""


# Create a new allergy record
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_allergy(
    allergy: Allergy,
    session: Session = Depends(get_session),
):
    """
    Create a new allergy record for a patient.
    By default, status is set to 'Active'.
    """
    # Verify the patient exists before adding an allergy
    patient = session.exec(
        select(Patient).where(Patient.id == allergy.patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Set creation timestamp and save
    allergy.created_at = datetime.utcnow()
    session.add(allergy)
    session.commit()
    session.refresh(allergy)

    return {
        "message": "Allergy record created successfully",
        "allergy_id": allergy.id,
    }


# Get all allergies for a patient
@router.get("/{patient_id}")
async def get_patient_allergies(
    patient_id: int,
    session: Session = Depends(get_session),
):
    """
    Get all allergies for a patient, ordered by creation date descending.
    """
    # Verify patient exists
    patient = session.exec(
        select(Patient).where(Patient.id == patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Query allergies, newest first
    allergies = session.exec(
        select(Allergy)
        .where(Allergy.patient_id == patient_id)
        .order_by(Allergy.created_at.desc())
    ).all()

    return allergies


# Get a single allergy by ID
@router.get("/{patient_id}/{allergy_id}")
async def get_allergy(
    patient_id: int,
    allergy_id: int,
    session: Session = Depends(get_session),
):
    """
    Get a single allergy record by its ID.
    """
    allergy = session.exec(
        select(Allergy).where(
            Allergy.patient_id == patient_id,
            Allergy.id == allergy_id,
        )
    ).first()

    if not allergy:
        raise HTTPException(status_code=404, detail="Allergy record not found")

    return allergy


# Update the status of an allergy
@router.patch("/{patient_id}/{allergy_id}/status")
async def update_allergy_status(
    patient_id: int,
    allergy_id: int,
    update_data: dict,  # Expecting: {"status": "Inactive", "status_reason": "...", "updated_by": "..."}
    session: Session = Depends(get_session),
):
    """
    Update the status of an allergy record.
    Allergies cannot be deleted, but status can be changed (e.g., Active, Inactive).
    """
    # Find the allergy matching patient_id and allergy_id
    allergy = session.exec(
        select(Allergy).where(
            Allergy.patient_id == patient_id,
            Allergy.id == allergy_id,
        )
    ).first()

    if not allergy:
        raise HTTPException(status_code=404, detail="Allergy record not found")

    # Validate that status is provided in request body
    new_status = update_data.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="status is required")

    # Update only the allowed status fields
    allergy.status = new_status
    
    # Optional fields
    if "status_reason" in update_data:
        allergy.status_reason = update_data["status_reason"]
    if "updated_by" in update_data:
        allergy.updated_by = update_data["updated_by"]

    session.commit()
    session.refresh(allergy)

    return {
        "message": "Allergy status updated successfully",
        "allergy_id": allergy.id,
        "new_status": allergy.status,
    }