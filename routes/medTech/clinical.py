import httpx
import uuid
from fastapi import APIRouter, HTTPException
from dotenv import load_dotenv
import os

load_dotenv()

router = APIRouter(prefix="/medTech/clinical", tags=["clinical"])

# NHS SANDBOX ENDPOINTS
AUTH_URL = "https://sandbox.api.service.nhs.uk/oauth2/token"
SCR_URL = "https://sandbox.api.service.nhs.uk/summary-care-record/FHIR/R4"
NRL_URL = "https://sandbox.api.service.nhs.uk/record-locator/producer/FHIR/R4"

# NHS DEVELOPER PORTAL CREDENTIALS (Replace with your keys)
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

async def get_nhs_access_token():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            AUTH_URL,
            # Some sandbox accounts require x-www-form-urlencoded
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
        
        # Log the error to your terminal so you can see why it's failing
        if response.status_code != 200:
            print(f"NHS AUTH ERROR: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=500, 
                detail=f"NHS Auth failed: {response.text}"
            )
        
        return response.json().get("access_token")

@router.get("/{nhs_number}/scr")
async def get_scr(nhs_number: str):
    # Returning dummy SCR data for UI
    return {
        "structured_data": {
            "allergies": [
                { "name": "Penicillin", "criticality": "High" },
                { "name": "Peanuts", "criticality": "Low" }
            ],
            "medications": [
                { "name": "Apixaban 5mg - Once Daily", "status": "Active", "clinician": "Smith" },
                { "name": "Metformin 500mg", "status": "Suspended", "clinician": "Doe" }
            ]
        }
    }

@router.get("/{nhs_number}/nrl")
async def get_nrl(nhs_number: str):
    # Returning dummy NRL document pointers for UI
    return {
        "pointers": [
            { "type": "Discharge Summary - Leeds Teaching Hospital", "provider": "Leeds Teaching Hospital", "date": "2024-03-10" },
            { "type": "Chest X-Ray - PA View", "provider": "St. James's Hospital", "date": "2024-02-15" },
            { "type": "Clinic Letter URL", "provider": "General Practice", "date": "2024-01-22" }
        ]
    }