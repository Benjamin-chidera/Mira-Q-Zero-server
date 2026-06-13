import random
import datetime
from sqlalchemy import text
from sqlmodel import Session, select
from database import engine, create_db_and_tables
from models import Patient, User


def run_migrations():
    """Add new columns to patient table if they don't already exist."""
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE patient ADD COLUMN gender VARCHAR"))
            conn.execute(text("ALTER TABLE patient ADD COLUMN date_of_birth VARCHAR"))
            conn.execute(text("ALTER TABLE patient ADD COLUMN age INTEGER"))
        except Exception as e:
            print("Columns might already exist:", e)


def clear_patient_table():
    """Delete all existing patients from the table."""
    with Session(engine) as session:
        all_patients = session.exec(select(Patient)).all()
        for patient in all_patients:
            session.delete(patient)
        session.commit()
        print(f"Cleared {len(all_patients)} patients from the database.")


def generate_random_patients(num=10):
    """
    Generate a list of unique random patients.
    Each patient has a unique combination of name + gender + date_of_birth
    to prevent duplicate registration.
    """
    first_names = [
        "John", "Jane", "Alice", "Bob", "Charlie",
        "Diana", "Eve", "Frank", "Grace", "Henry",
        "Ivy", "Jack", "Karen", "Leo",
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Jones", "Brown",
        "Davis", "Miller", "Wilson", "Moore", "Taylor",
        "Anderson", "Thomas", "Jackson", "White",
    ]
    genders = ["Male", "Female"]

    patients = []
    # Track unique combinations to avoid duplicates within the seed batch
    seen_combinations = set()

    while len(patients) < num:
        first_name = random.choice(first_names)
        last_name = random.choice(last_names)
        full_name = f"{first_name} {last_name}"
        gender = random.choice(genders)

        # Generate random date of birth between 1940 and 2010
        start_date = datetime.date(1940, 1, 1)
        end_date = datetime.date(2010, 12, 31)
        days_range = (end_date - start_date).days
        random_days = random.randrange(days_range)
        dob = start_date + datetime.timedelta(days=random_days)
        dob_string = dob.strftime("%Y-%m-%d")

        # Calculate age based on today's date
        today = datetime.date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        # Generate unique 10-digit NHS number
        nhs_number = str(random.randint(1000000000, 9999999999))

        # Create a unique key from name + gender + dob to prevent duplicates
        unique_key = (full_name, gender, dob_string)

        if unique_key in seen_combinations:
            # Skip this patient — same name + gender + dob already exists in our batch
            continue

        seen_combinations.add(unique_key)

        patient = Patient(
            name=full_name,
            gender=gender,
            date_of_birth=dob_string,
            age=age,
            nhs_number=nhs_number,
        )
        patients.append(patient)

    return patients


from main import seed_default_admin, seed_default_doctors


def seed_db():
    """Clear the patient table, then seed patients distributed across doctors."""
    create_db_and_tables()
    run_migrations()

    # Ensure admin and practitioners are seeded first
    seed_default_admin()
    seed_default_doctors()

    # Clear the table first
    clear_patient_table()

    # Generate 9 random patients (we explicitly add 1 specific patient first, making 10 total)
    patients = generate_random_patients(9)

    with Session(engine) as session:
        # Fetch all practitioners
        doctors = session.exec(select(User).where(User.role == "practitioner")).all()
        if not doctors:
            print("No doctors found in the database. Please run the server lifespan first to seed doctors.")
            return

        # Find Benjamin Chidera
        benjamin = next((d for d in doctors if d.email == "benjaminchidera72@gmail.com"), None)
        if not benjamin:
            print("Benjamin Chidera not found. Assigning to the first available doctor.")
            benjamin = doctors[0]

        # Seed Benjamin Chidera Benjamin explicitly
        dob_string = "1995-10-22"
        calculated_age = 30
        benjamin_patient = Patient(
            name="Benjamin Chidera Benjamin",
            gender="Male",
            date_of_birth=dob_string,
            age=calculated_age,
            nhs_number="9399227418",
            doctor_id=benjamin.id,
        )
        session.add(benjamin_patient)
        print(f"Added patient 'Benjamin Chidera Benjamin' assigned to {benjamin.name}.")

        # Distribute the other 9 patients round-robin among ALL 5 doctors
        added_count = 0
        for p in patients:
            # We cycle through all doctors
            assigned_doc = doctors[added_count % len(doctors)]
            p.doctor_id = assigned_doc.id
            session.add(p)
            added_count += 1

        session.commit()
        print(f"Successfully seeded {added_count + 1} patients in the database.")


if __name__ == "__main__":
    seed_db()
