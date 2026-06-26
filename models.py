from sqlmodel import SQLModel, Field, Column
from sqlalchemy import LargeBinary, TEXT
from datetime import datetime
from typing import Optional


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: Optional[str] = Field(default=None)
    name: str
    role: str = Field(default="practitioner")  # "admin" or "practitioner"
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Patient(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    nhs_number: str = Field(unique=True, index=True)
    gender: Optional[str] = Field(default=None)
    date_of_birth: Optional[str] = Field(default=None)
    age: int = Field(default=None)
    doctor_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class GPSlot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    gp_ods_code: str = Field(index=True)
    practitioner_name: str
    date: str
    time: str
    is_booked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Booking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reference_number: str = Field(unique=True, index=True)
    gp_ods_code: str
    patient_nhs_number: str
    slot_id: int = Field(foreign_key="gpslot.id")
    patient_name: Optional[str] = Field(default=None)
    patient_phone: Optional[str] = Field(default=None)
    patient_email: Optional[str] = Field(default=None)
    symptoms: Optional[str] = Field(default=None)
    appointment_date: Optional[str] = Field(default=None)
    appointment_time: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Patient Documents (discharge summaries, clinical letters, etc.)   
class PatientDocument(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    title: str 
    content: str = Field(default=None, sa_column=Column(TEXT, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Document Amendments (updates, corrections, or annotations added to documents after their initial creation.)
class DocumentAmendment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    document_id: int = Field(foreign_key="patientdocument.id", index=True)
    amendment_text: str = Field(sa_column=Column(TEXT, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)

class MedicalGuidelineCache(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    keyword: str = Field(unique=True, index=True) # e.g. "metformin"
    guidelines_json: str = Field(sa_column=Column(TEXT, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)

class PatientNotification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    title: str
    message: str
    severity: str = Field(default="Medium") # "High", "Medium", "Low"
    status: str = Field(default="Unresolved") # "Unresolved", "Resolved", "Acknowledged"
    conversation_id: Optional[str] = Field(default=None, foreign_key="researchconversation.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

# PACS Imaging (X-rays, CT scans, MRIs, etc)
class PACSImaging(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    accession_number: str = Field(unique=True, index=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    modality: str  # e.g. "CT", "XRAY", "MRI", "ULTRASOUND"
    body_site: str = Field(default=None) # e.g. "Chest", "Head", "Abdomen"
    reason_for_scan: str = Field(default=None)
    image_path: str = Field(default=None)  # path to .jpg file
    radiologist_report: str = Field(default=None, sa_column=Column(TEXT, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Operative Notes (surgical treatments)
class OperativeNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    procedure_name: str
    procedure_performed: str
    pre_op_diagnosis: str = Field(default=None)
    post_op_diagnosis: str = Field(default=None)
    narrative_text: str = Field(default=None, sa_column=Column(TEXT, nullable=True))
    post_op_instructions: str = Field(default=None, sa_column=Column(TEXT, nullable=True)) 
    surgeon_name: str = Field(default=None)
    surgery_date: str = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ClinicalNotes(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    content: str = Field(sa_column=Column(TEXT, nullable=False))
    author: str  ## Author can be a GP or any healthcare practitioner   
    author_role: str = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Allergy(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    substance: str
    criticality: Optional[str] = Field(default=None, nullable=True)  # e.g. "high", "low", "unable-to-assess"
    reaction: Optional[str] = Field(default=None, nullable=True)  # e.g. "rash", "anaphylaxis", "nausea"
    status: str = Field(default="Active")  # e.g. "Active", "Inactive"  
    updated_by: Optional[str] = Field(default=None, nullable=True)
    status_reason: Optional[str] = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Medication(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    drug_name: str
    dosage: Optional[str] = Field(default=None, nullable=True)
    frequency: Optional[str] = Field(default=None, nullable=True)
    updated_by: Optional[str] = Field(default=None, nullable=True)
    status_reason: Optional[str] = Field(default=None, nullable=True)
    status: str = Field(default="Active")  # e.g. "Active", "Stopped", "Completed"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PatientSummaryCache(SQLModel, table=True):
    patient_id: int = Field(primary_key=True, foreign_key="patient.id", index=True)
    summary_json: str = Field(sa_column=Column(TEXT, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow)
