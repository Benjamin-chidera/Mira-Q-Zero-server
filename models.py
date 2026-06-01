from sqlmodel import SQLModel, Field
from sqlalchemy import LargeBinary
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
    age: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Allergy(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    substance: str
    criticality: Optional[str] = Field(default=None)  # e.g. "high", "low", "unable-to-assess"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Medication(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    drug_name: str
    dosage: Optional[str] = Field(default=None)
    frequency: Optional[str] = Field(default=None)
    status: str = Field(default="Active")  # e.g. "Active", "Stopped", "Completed"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OperativeNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    procedure_name: str
    pre_op_diagnosis: Optional[str] = Field(default=None)
    narrative_text: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PACSImaging(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    modality: str  # e.g. "CT", "XRAY", "MRI", "ULTRASOUND"
    image_path: Optional[str] = Field(default=None)  # path to .jpg file
    radiologist_report: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PatientDocument(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    file_type: str  # e.g. "pdf", "docx", "png"
    title: str
    file: Optional[bytes] = Field(default=None, sa_type=LargeBinary)
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
