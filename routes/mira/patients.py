import httpx
import uuid
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/medTech/patients", tags=["patients"])

# Instead of searching by practice, get a single patient by their NHS Number
PDS_SINGLE_PATIENT_URL = "https://sandbox.api.service.nhs.uk/personal-demographics/FHIR/R4/Patient"



request_id = str(uuid.uuid4())
headers = {
    "Accept": "application/fhir+json",
    "X-Request-ID": request_id,
}   

from database import get_session
from models import Patient, Booking
from sqlmodel import select
from fastapi import Depends
from sqlmodel import Session

@router.get("/")
async def get_practice_patients(ods_code: str = "B82617", session: Session = Depends(get_session)):
    # In dev, we don't 'search' PDS. We fetch our known patients.
    patients = []
    
    # 1. Fetch from local Database
    db_patients = session.exec(select(Patient)).all()
    seen_nhs_numbers = set()
    for p in db_patients:
        # Find bookings for this patient by matching on patient_name
        patient_bookings = session.exec(
            select(Booking).where(Booking.patient_name == p.name)
        ).all()

        patients.append({
            "id": p.id,
            "nhsNumber": p.nhs_number,
            "name": p.name,
            "age": p.age,
            "gender": p.gender,
            "dateOfBirth": p.date_of_birth,
            "status": "Review",
            "reason": patient_bookings[0].symptoms if patient_bookings else "Not set yet"
        })
        seen_nhs_numbers.add(p.nhs_number)
        
    return {"patients": patients}


@router.patch("/{patient_id}")
async def update_patient_details(
    patient_id: int,
    data: dict,
    session: Session = Depends(get_session),
):
    """
    Update patient details like name, nhs_number, gender, date_of_birth, age.
    """
    patient = session.exec(select(Patient).where(Patient.id == patient_id)).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if "name" in data:
        patient.name = data["name"]
    if "nhs_number" in data:
        patient.nhs_number = data["nhs_number"]
    if "gender" in data:
        patient.gender = data["gender"]
    if "date_of_birth" in data:
        patient.date_of_birth = data["date_of_birth"]
    if "age" in data:
        try:
            patient.age = int(data["age"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Age must be an integer")

    session.commit()
    session.refresh(patient)

    return {
        "message": "Patient details updated successfully",
        "patient": {
            "id": patient.id,
            "nhsNumber": patient.nhs_number,
            "name": patient.name,
            "age": patient.age,
            "gender": patient.gender,
            "dateOfBirth": patient.date_of_birth,
        }
    }