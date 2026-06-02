from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from starlette import status
from sqlmodel import Session, select
from database import get_session
from models import PACSImaging, Patient
from datetime import datetime
import os
import uuid
"""
- like X-Rays, CT scans, MRIs, and Ultrasounds
"""

"""
PACS Imaging — X-Rays, CT scans, MRIs, and Ultrasounds.

PACS records are NEVER deleted or overwritten.
Each new scan creates a new record (append-only).
If a patient gets a chest X-ray on Monday and another on Friday,
the hospital keeps both so clinicians can track progression.
"""

router = APIRouter(prefix="/mira/pacs_imaging", tags=["mira-pacs-imaging"])

PACS_UPLOAD_DIR = os.path.join("patient_docs", "pacs_imaging")

# Ensure the upload directory exists
os.makedirs(PACS_UPLOAD_DIR, exist_ok=True)


# add a new imaging record with image upload
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_imaging_record(
    patient_id: int = Form(...),
    accession_number: str = Form(...),
    modality: str = Form(...),
    body_site: str = Form(None),
    reason_for_scan: str = Form(None),
    radiologist_report: str = Form(None),
    image: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """
    Create a new PACS imaging record with an uploaded image.
    Each scan is a new record — existing scans are never overwritten.
    """
    # Verify patient exists
    patient = session.exec(
        select(Patient).where(Patient.id == patient_id)
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Check the accession number is unique
    existing = session.exec(
        select(PACSImaging).where(
            PACSImaging.accession_number == accession_number
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Accession number '{accession_number}' already exists",
        )

    # Get the file extension from the uploaded image
    file_extension = ""
    if image.filename:
        file_extension = image.filename.rsplit(".", 1)[-1].lower()

    # Save the image to disk with a unique filename
    unique_filename = f"{uuid.uuid4().hex}.{file_extension}"
    file_path = os.path.join(PACS_UPLOAD_DIR, unique_filename)

    with open(file_path, "wb") as buffer:
        buffer.write(await image.read())

    # Save the record in the database
    record = PACSImaging(
        patient_id=patient_id,
        accession_number=accession_number,
        modality=modality.upper(),
        body_site=body_site,
        reason_for_scan=reason_for_scan,
        image_path=file_path,
        radiologist_report=radiologist_report,
        created_at=datetime.utcnow(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    return {
        "message": "Imaging record created successfully",
        "imaging_id": record.id,
        "accession_number": record.accession_number,
        "image_path": record.image_path,
    }


# get all imaging records for a patient
@router.get("/{patient_id}")
async def get_patient_imaging(
    patient_id: int,
    session: Session = Depends(get_session),
):
    """
    Get all imaging records for a patient, ordered by most recent first.
    """
    records = session.exec(
        select(PACSImaging) 
        .where(PACSImaging.patient_id == patient_id)
        .order_by(PACSImaging.created_at.desc())
    ).all()

    return records


# get all imaging records for a patient filtered by modality
@router.get("/{patient_id}/modality/{modality}")
async def get_patient_imaging_by_modality(
    patient_id: int,
    modality: str,
    session: Session = Depends(get_session),
):
    """
    Get imaging records for a patient filtered by modality (e.g. XRAY, CT, MRI).
    Useful for comparing scans of the same type over time.
    """
    records = session.exec(
        select(PACSImaging)
        .where(
            PACSImaging.patient_id == patient_id,
            PACSImaging.modality == modality.upper(),
        )
        .order_by(PACSImaging.created_at.desc())
    ).all()

    return records


# get a single imaging record by id
@router.get("/{patient_id}/{imaging_id}")
async def get_imaging_record(
    patient_id: int,
    imaging_id: int,
    session: Session = Depends(get_session),
):
    """
    Get a single imaging record by its ID.
    """
    record = session.exec(
        select(PACSImaging).where(
            PACSImaging.patient_id == patient_id,
            PACSImaging.id == imaging_id,
        )
    ).first()

    if not record:
        raise HTTPException(status_code=404, detail="Imaging record not found")

    return record


# add a radiologist report to an existing imaging record
@router.patch("/{patient_id}/{imaging_id}/report")
async def add_radiologist_report(
    patient_id: int,
    imaging_id: int,
    report: dict,
    session: Session = Depends(get_session),
):
    """
    Add or update the radiologist report on an imaging record.
    This is the only field that can be updated — the scan itself is immutable.
    """
    record = session.exec(
        select(PACSImaging).where(
            PACSImaging.patient_id == patient_id,
            PACSImaging.id == imaging_id,
        )
    ).first()

    if not record:
        raise HTTPException(status_code=404, detail="Imaging record not found")

    radiologist_report = report.get("radiologist_report")
    if not radiologist_report:
        raise HTTPException(status_code=400, detail="radiologist_report is required")

    record.radiologist_report = radiologist_report
    session.commit()
    session.refresh(record)

    return {
        "message": "Radiologist report added successfully",
        "imaging_id": record.id,
    }


# serve the scan image
@router.get("/{patient_id}/{imaging_id}/image")
async def get_imaging_image(
    patient_id: int,
    imaging_id: int,
    session: Session = Depends(get_session),
):
    """
    Serve the actual scan image file.
    Use this URL as an img src on the frontend.
    """
    record = session.exec(
        select(PACSImaging).where(
            PACSImaging.patient_id == patient_id,
            PACSImaging.id == imaging_id,
        )
    ).first()

    if not record or not record.image_path:
        raise HTTPException(status_code=404, detail="Image not found")

    if not os.path.exists(record.image_path):
        raise HTTPException(status_code=404, detail="Image file not found on server")

    return FileResponse(path=record.image_path)