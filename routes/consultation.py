from fastapi import APIRouter
from pydantic import BaseModel
from utils.verify_patient_and_get_nhs_number import verify_patient_and_get_nhs_number

router = APIRouter(prefix="/consultation", tags=["consultation"])


class PatientVerify(BaseModel):
    given_name: str
    family_name: str
    dob: str       # normalized to YYYY-MM-DD by the frontend
    postcode: str
    gender: str = ""

  
class ConsultationSubmit(BaseModel):
    patient_name: str
    email: str
    phone: str
    gp_name: str
    symptoms: str


@router.post("/verify-patient")
async def verify_patient(data: PatientVerify):
    nhs_number = await verify_patient_and_get_nhs_number(
        family_name=data.family_name,
        given_name=data.given_name,
        dob=data.dob,
        postcode=data.postcode,
        gender=data.gender,
    )
    return {"nhs_number": nhs_number}


@router.post("/submit")
async def submit_consultation(data: ConsultationSubmit):
    print(
        f"[Consultation] {data.patient_name} → {data.gp_name} | "
        f"Symptoms: {data.symptoms} | Contact: {data.email} / {data.phone}"
    )
    return {
        "status": "submitted",
        "message": f"Consultation request sent to {data.gp_name}",
    }
