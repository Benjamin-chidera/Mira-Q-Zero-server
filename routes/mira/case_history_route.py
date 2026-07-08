import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_session
from models import Patient
from utils.mira.case_history.history import CaseHistory

router = APIRouter(prefix="/mira/case-history", tags=["mira-case-history"])

@router.get("")
def get_case_history(
    practitioner_id: int,
    status: Optional[str] = None,
    mode: str = "research",
    session: Session = Depends(get_session)
):
    """
    Retrieves case history items for a specific practitioner.
    If mode == "patient", queries the Patient table for completed/failed/abandoned outcomes.
    If mode == "research", queries the CaseHistory table for AI researcher conversations.
    """
    if mode == "patient":
        # Fetch patients with a logged outcome status (not Review)
        stmt = select(Patient).where(
            Patient.doctor_id == practitioner_id
        ).where(
            Patient.status != "Review"
        ).order_by(Patient.created_at.desc())
        patients = session.exec(stmt).all()

        result = []
        for p in patients:
            client_status = "success" if p.status == "Complete" else p.status.lower()

            # If status filter is active, check match
            if status and status != "all" and client_status != status.lower():
                continue

            result.append({
                "id": f"patient_{p.id}",
                "title": f"Patient: {p.name}",
                "preview": f"Outcome: {p.status}. Reason: {p.outcome_reason or 'No reason provided'}",
                "status": client_status,
                "status_reason": p.outcome_reason,
                "date": p.created_at.strftime("%b %d") if p.created_at else "",
                "timestamp": p.created_at.strftime("%H:%M") if p.created_at else ""
            })
        return result

    # Default/Research cases
    stmt = select(CaseHistory).where(CaseHistory.practitioner_id == practitioner_id).order_by(CaseHistory.updated_at.desc())
    items = session.exec(stmt).all()

    result = []
    for item in items:
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
    mode: str = "research",
    session: Session = Depends(get_session)
):
    """
    Retrieves full details for a specific case history item.
    If mode == "patient" (or id starts with patient_), returns structured patient details.
    Otherwise returns conversation messages.
    """
    if mode == "patient" or conversation_id.startswith("patient_"):
        patient_id_str = conversation_id.replace("patient_", "")
        try:
            patient_id = int(patient_id_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid patient ID")

        patient = session.get(Patient, patient_id)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient case not found")

        client_status = "success" if patient.status == "Complete" else patient.status.lower()
        detail_content = f"### Patient Case Summary\n\n" \
                         f"- **Name:** {patient.name}\n" \
                         f"- **NHS Number:** {patient.nhs_number}\n" \
                         f"- **Age / Gender:** {patient.age} / {patient.gender or 'Unknown'}\n" \
                         f"- **Case Status:** {patient.status}\n" \
                         f"- **Outcome Reason:** {patient.outcome_reason or 'No reason provided'}"

        messages = [
            {"role": "user", "content": f"View case outcome details for patient {patient.name} (NHS: {patient.nhs_number})"},
            {"role": "agent", "content": detail_content}
        ]

        return {
            "id": conversation_id,
            "title": f"Patient: {patient.name}",
            "preview": f"Outcome: {patient.status}",
            "status": client_status,
            "status_reason": patient.outcome_reason,
            "date": patient.created_at.strftime("%b %d") if patient.created_at else "",
            "messages": messages
        }

    # Default/Research case details
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
