import random
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel
from database import get_session
from models import Booking, GPSlot

router = APIRouter()


class BookingRequest(BaseModel):
    ods_code: str
    slot_id: int
    nhs_number: str
    patient_name: str | None = None
    patient_phone: str | None = None
    patient_email: str | None = None
    symptoms: str | None = None



@router.post("/bookings", status_code=201)
def create_booking(request: BookingRequest, session: Session = Depends(get_session)):
    slot = session.get(GPSlot, request.slot_id)

    if not slot or slot.gp_ods_code != request.ods_code:
        raise HTTPException(status_code=404, detail="Slot not found")

    if slot.is_booked:
        raise HTTPException(status_code=409, detail="This slot has already been booked")

    # Check if this patient already has a booking with this GP
    existing_booking = session.exec(
        select(Booking).where(
            Booking.patient_nhs_number == request.nhs_number,
            Booking.gp_ods_code == request.ods_code,
        )
    ).first()

    if existing_booking:
        booked_slot = session.get(GPSlot, existing_booking.slot_id)
        detail = {
            "already_booked": True,
            "message": "You already have a booking with this GP.",
            "reference_number": existing_booking.reference_number,
            "date": booked_slot.date if booked_slot else "unknown",
            "time": booked_slot.time if booked_slot else "unknown",
            "practitioner_name": booked_slot.practitioner_name if booked_slot else "your GP",
        }
        raise HTTPException(status_code=409, detail=detail)

    # Generate a unique reference number
    while True:
        reference = f"CNF-{random.randint(10000, 99999)}"
        existing = session.exec(select(Booking).where(Booking.reference_number == reference)).first()
        if not existing:
            break

    booking = Booking(
        reference_number=reference,
        gp_ods_code=request.ods_code,
        patient_nhs_number=request.nhs_number,
        slot_id=request.slot_id,
        patient_name=request.patient_name,
        patient_phone=request.patient_phone,
        patient_email=request.patient_email,
        symptoms=request.symptoms,
    )
    slot.is_booked = True
    session.add(booking)
    session.add(slot)
    session.commit()
    session.refresh(booking)

    return {
        "reference_number": reference,
        "slot": {"date": slot.date, "time": slot.time},
        "gp_ods_code": request.ods_code,
        "practitioner_name": slot.practitioner_name,
    }
