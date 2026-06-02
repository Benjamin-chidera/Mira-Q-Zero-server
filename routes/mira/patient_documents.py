from fastapi import APIRouter, HTTPException, Depends
from starlette import status
from sqlmodel import Session, select
from database import get_session
from models import PatientDocument, DocumentAmendment, Patient
from datetime import datetime

router = APIRouter(prefix="/mira/patient_documents", tags=["mira-patient_documents"])

"""
It stores files like discharge summaries, clinical letters, and lab result trackers
"""


# ─── Patient Document Endpoints ──────────────────────────────────────────────

# create a new patient document
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_document(
    document: PatientDocument,
    session: Session = Depends(get_session),
):
    """
    Create a new patient document (discharge summary, clinical letter, etc).
    """
    # Verify patient exists
    patient = session.exec(
        select(Patient).where(Patient.id == document.patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    document.created_at = datetime.utcnow()
    session.add(document)
    session.commit()
    session.refresh(document)

    return {
        "message": "Document created successfully",
        "document_id": document.id,
    }


# get all documents for a patient
@router.get("/{patient_id}")
async def get_documents(
    patient_id: int,
    session: Session = Depends(get_session),
):
    """
    Get all documents for a patient.
    """
    documents = session.exec(
        select(PatientDocument).where(PatientDocument.patient_id == patient_id)
    ).all()

    return documents


# get a single document by id
@router.get("/{patient_id}/{document_id}")
async def get_document(
    patient_id: int,
    document_id: int,
    session: Session = Depends(get_session),
):
    """
    Get a single patient document by id.
    """
    doc = session.exec(
        select(PatientDocument).where(
            PatientDocument.patient_id == patient_id,
            PatientDocument.id == document_id,
        )
    ).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return doc


# ─── Document Amendment Endpoints ─────────────────────────────────────────────

# add an amendment to a document
@router.post("/{patient_id}/{document_id}/amendments", status_code=status.HTTP_201_CREATED)
async def create_amendment(
    patient_id: int,
    document_id: int,
    amendment: DocumentAmendment,
    session: Session = Depends(get_session),
):
    """
    Add an amendment to a patient document.
    Used when a doctor wants to amend or correct something in the document.
    """
    # Verify the document exists for this patient
    doc = session.exec(
        select(PatientDocument).where(
            PatientDocument.patient_id == patient_id,
            PatientDocument.id == document_id,
        )
    ).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Set the IDs from the path params so they match
    amendment.patient_id = patient_id
    amendment.document_id = document_id
    amendment.created_at = datetime.utcnow()

    session.add(amendment)
    session.commit()
    session.refresh(amendment)

    return {
        "message": "Amendment added successfully",
        "amendment_id": amendment.id,
    }


# get all amendments for a document
@router.get("/{patient_id}/{document_id}/amendments")
async def get_amendments(
    patient_id: int,
    document_id: int,
    session: Session = Depends(get_session),
):
    """
    Get all amendments for a specific patient document.
    Returns them in chronological order so you can see the amendment history.
    """
    # Verify the document exists
    doc = session.exec(
        select(PatientDocument).where(
            PatientDocument.patient_id == patient_id,
            PatientDocument.id == document_id,
        )
    ).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    amendments = session.exec(
        select(DocumentAmendment).where(
            DocumentAmendment.document_id == document_id
        )
    ).all()

    return amendments
