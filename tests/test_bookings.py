from sqlmodel import Session, select
from models import GPSlot, Booking

def test_create_booking_success(client, session: Session):
    # 1. Arrange: insert a GPSlot in the database
    slot = GPSlot(
        gp_ods_code="ODS123",
        practitioner_name="Dr. House",
        date="2026-06-03",
        time="10:00",
        is_booked=False,
    )
    session.add(slot)
    session.commit()
    session.refresh(slot)

    # 2. Act: make booking request to the prefixed endpoint
    payload = {
        "ods_code": "ODS123",
        "slot_id": slot.id,
        "nhs_number": "1234567890",
        "patient_name": "John Doe",
        "patient_phone": "07700900077",
        "patient_email": "john@example.com",
        "symptoms": "Fever",
    }
    response = client.post("/api/bookings", json=payload)

    # 3. Assert response
    assert response.status_code == 201
    data = response.json()
    assert "reference_number" in data
    assert data["gp_ods_code"] == "ODS123"
    assert data["practitioner_name"] == "Dr. House"
    assert data["slot"]["date"] == "2026-06-03"

    # Refresh DB session state and assert DB changes
    session.refresh(slot)
    assert slot.is_booked is True

    # Check booking record in DB
    booking = session.exec(select(Booking).where(Booking.reference_number == data["reference_number"])).first()
    assert booking is not None
    assert booking.patient_name == "John Doe"
