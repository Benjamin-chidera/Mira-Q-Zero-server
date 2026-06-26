from fastapi import APIRouter, HTTPException, Depends
from starlette import status
from sqlmodel import Session, select
from database import get_session
from models import PatientNotification, Patient
from typing import Dict, Any

router = APIRouter(prefix="/mira/notifications", tags=["mira-notifications"])

@router.get("/{patient_id}")
async def get_patient_notifications(
    patient_id: int,
    session: Session = Depends(get_session)
):
    """
    Get all clinical notifications/alerts for a patient, ordered by creation date descending.
    """
    # Verify patient exists
    patient = session.exec(
        select(Patient).where(Patient.id == patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    notifications = session.exec(
        select(PatientNotification)
        .where(PatientNotification.patient_id == patient_id)
        .order_by(PatientNotification.created_at.desc())
    ).all()

    return notifications

@router.patch("/{notification_id}/status")
async def update_notification_status(
    notification_id: int,
    payload: Dict[str, Any],
    session: Session = Depends(get_session)
):
    """
    Update status of a clinical notification (e.g., Acknowledged or Resolved).
    """
    notification = session.get(PatientNotification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    new_status = payload.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="status field is required")

    valid_statuses = ["Unresolved", "Resolved", "Acknowledged"]
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {valid_statuses}"
        )

    notification.status = new_status
    session.add(notification)
    session.commit()
    session.refresh(notification)

    return {
        "message": "Notification status updated successfully",
        "notification_id": notification.id,
        "status": notification.status
    }
