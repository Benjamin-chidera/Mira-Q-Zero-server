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
from models import Patient
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
        patients.append({
            "id": p.id,
            "nhsNumber": p.nhs_number,
            "name": p.name,
            "age": p.age,
            "gender": p.gender,
            "status": "Review",
            "reason": "Fetched via local database"
        })
        seen_nhs_numbers.add(p.nhs_number)
        
    return {"patients": patients}