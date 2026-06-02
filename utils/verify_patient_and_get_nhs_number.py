import httpx
import uuid
import random
import datetime
from sqlmodel import Session, select
from database import engine
from models import Patient


# NHS Personal Demographics Service (PDS) Sandbox endpoint
PDS_SANDBOX_URL = "https://sandbox.api.service.nhs.uk/personal-demographics/FHIR/R4/Patient"


def _calculate_age(dob_string: str) -> int | None:
    """
    Calculate age from a date of birth string in YYYY-MM-DD format.
    Returns None if the format is invalid.
    """
    try:
        dob = datetime.date.fromisoformat(dob_string)
        today = datetime.date.today()
        # Subtract 1 if birthday hasn't happened yet this year
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return age
    except (ValueError, TypeError):
        return None
 

def _generate_unique_nhs_number() -> str:
    with Session(engine) as session:
        while True:
            candidate = str(random.randint(1_000_000_000, 9_999_999_999))
            exists = session.exec(select(Patient).where(Patient.nhs_number == candidate)).first()
            if not exists:
                return candidate


def _save_patient(
    name: str,
    nhs_number: str,
    gender: str = "",
    date_of_birth: str = "",
    age: int | None = None,
) -> None:
    """
    Save a patient to the database with all demographic fields.
    If a patient with the same NHS number already exists, update any missing fields.
    Also checks for duplicate patients by name + gender + DOB to prevent double registration.
    """
    with Session(engine) as session:
        # Check if a patient with this NHS number already exists
        existing_by_nhs = session.exec(
            select(Patient).where(Patient.nhs_number == nhs_number)
        ).first()

        if existing_by_nhs:
            # Update any missing demographic fields on the existing record
            if gender and not existing_by_nhs.gender:
                existing_by_nhs.gender = gender
            if date_of_birth and not existing_by_nhs.date_of_birth:
                existing_by_nhs.date_of_birth = date_of_birth
            if age is not None and existing_by_nhs.age is None:
                existing_by_nhs.age = age
            session.add(existing_by_nhs)
            session.commit()
            return

        # Check for duplicate patient by name + gender + date_of_birth
        # This prevents the same person from being registered twice with a different NHS number
        if name and gender and date_of_birth:
            duplicate = session.exec(
                select(Patient).where(
                    Patient.name == name,
                    Patient.gender == gender,
                    Patient.date_of_birth == date_of_birth,
                )
            ).first()

            if duplicate:
                # Patient already exists with same demographics — skip creation
                return

        # Create a new patient with all demographic fields
        new_patient = Patient(
            name=name,
            nhs_number=nhs_number,
            gender=gender if gender else None,
            date_of_birth=date_of_birth if date_of_birth else None,
            age=age,
        )
        session.add(new_patient)
        session.commit()


async def verify_patient_and_get_nhs_number(
    family_name: str,
    given_name: str,
    dob: str,
    postcode: str,
    gender: str = "",
):
    """
    Searches the NHS PDS Sandbox for a patient matching the given demographics.
    Returns the NHS Number (string) if a match is found, or None if not.

    The Sandbox only has canned responses for very specific param combos.
    We try two search strategies:
      1. With postcode (the real-world approach)
      2. Without postcode but with gender hints (Sandbox fallback)

    Args:
        family_name: Patient's surname (e.g. "Smith")
        given_name:  Patient's first name (e.g. "Jane")
        dob:         Date of birth in YYYY-MM-DD format (e.g. "2010-10-22")
        postcode:    UK postcode (e.g. "LS1 6AE")
        gender:      Patient's gender (e.g. "female" or "male")
    """

    print(f"[PDS] Verifying patient: {given_name} {family_name}, DOB={dob}, Postcode={postcode}")

    # Calculate age from date of birth
    calculated_age = _calculate_age(dob)
    full_name = f"{given_name} {family_name}"

    # Strategy 1: Search with postcode (real-world approach)
    result = await _search_pds(
        family=family_name,
        given=given_name,
        birthdate=f"eq{dob}",
        extra_params={"address-postalcode": postcode},
    )

    if result is not None:
        _save_patient(full_name, result, gender=gender, date_of_birth=dob, age=calculated_age)
        return result

    # Strategy 2: Sandbox fallback — try with gender instead of postcode
    # The Sandbox only supports: family + given + gender + birthdate
    if gender:
        result = await _search_pds(
            family=family_name,
            given=given_name,
            birthdate=f"eq{dob}",
            extra_params={"gender": gender.lower()},
        )
        if result is not None:
            _save_patient(full_name, result, gender=gender, date_of_birth=dob, age=calculated_age)
            return result

    print("[PDS] No match found — generating a local NHS number.")
    nhs_number = _generate_unique_nhs_number()
    _save_patient(full_name, nhs_number, gender=gender, date_of_birth=dob, age=calculated_age)
    print(f"[PDS] Generated NHS Number: {nhs_number}")
    return nhs_number


async def _search_pds(
    family: str,
    given: str,
    birthdate: str,
    extra_params: dict,
) -> str | None:
    """
    Performs a single PDS search request.
    Returns the NHS Number if found, or None.
    """

    request_id = str(uuid.uuid4())

    headers = {
        "Accept": "application/fhir+json",
        "X-Request-ID": request_id,
        # In production, an OAuth2 Bearer token would go here
    }

    params = {
        "family": family,
        "given": given,
        "birthdate": birthdate,
    }
    # Merge in the extra search params (postcode or gender)
    params.update(extra_params)

    print(f"[PDS] Searching with params: {params}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(PDS_SANDBOX_URL, headers=headers, params=params)

    print(f"[PDS] Response status: {response.status_code}")

    # Only process successful responses
    if response.status_code != 200:
        print(f"[PDS] Non-200 response: {response.text[:500]}")
        return None

    data = response.json()

    # The Sandbox may return an OperationOutcome instead of a Bundle
    # when it doesn't recognise the search parameter combination
    resource_type = data.get("resourceType", "")
    if resource_type == "OperationOutcome":
        diagnostics = data.get("issue", [{}])[0].get("diagnostics", "No details")
        print(f"[PDS] OperationOutcome: {diagnostics}")
        return None

    # PDS returns a FHIR Bundle — check if any entries matched
    entries = data.get("entry", [])
    if len(entries) == 0:
        print("[PDS] Bundle returned but no entries.")
        return None

    # Take the first (best-scoring) match
    patient_resource = entries[0]["resource"]

    # The NHS Number lives in the 'identifier' array
    # Look for the identifier whose system contains "nhs-number"
    identifiers = patient_resource.get("identifier", [])
    nhs_number = None

    for identifier in identifiers:
        system = identifier.get("system", "")
        if "nhs-number" in system:
            nhs_number = identifier.get("value")
            break

    if nhs_number:
        print(f"[PDS] ✅ NHS Number found: {nhs_number}")
    else:
        print("[PDS] Patient found but no NHS Number in identifiers.")

    return nhs_number
