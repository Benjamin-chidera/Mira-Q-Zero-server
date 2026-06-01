import random
import datetime
from sqlalchemy import text
from sqlmodel import Session
from database import engine, create_db_and_tables
from models import Patient

def run_migrations():
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE patient ADD COLUMN gender VARCHAR"))
            conn.execute(text("ALTER TABLE patient ADD COLUMN date_of_birth VARCHAR"))
            conn.execute(text("ALTER TABLE patient ADD COLUMN age INTEGER"))
        except Exception as e:
            print("Columns might already exist:", e)

def generate_random_patients(num=10):
    first_names = ["John", "Jane", "Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Henry", "Ivy", "Jack", "Karen", "Leo"]
    last_names = ["Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson", "White"]
    genders = ["Male", "Female", "Non-binary", "Other"]

    patients = []
    for _ in range(num):
        first_name = random.choice(first_names)
        last_name = random.choice(last_names)
        gender = random.choice(genders)
        
        # Generate random date of birth between 1940 and 2010
        start_date = datetime.date(1940, 1, 1)
        end_date = datetime.date(2010, 12, 31)
        time_between_dates = end_date - start_date
        days_between_dates = time_between_dates.days
        random_number_of_days = random.randrange(days_between_dates)
        dob = start_date + datetime.timedelta(days=random_number_of_days)
        
        # Calculate age
        today = datetime.date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        
        # Generate random NHS number (10 digits)
        nhs_number = str(random.randint(1000000000, 9999999999))
        
        patient = Patient(
            name=f"{first_name} {last_name}",
            gender=gender,
            date_of_birth=dob.strftime("%Y-%m-%d"),
            age=age,
            nhs_number=nhs_number
        )
        patients.append(patient)
    return patients

def seed_db():
    create_db_and_tables()
    run_migrations()
    
    patients = generate_random_patients(20)
    
    with Session(engine) as session:
        for patient in patients:
            # Check if patient already exists
            existing = session.query(Patient).filter(Patient.nhs_number == patient.nhs_number).first()
            if not existing:
                session.add(patient)
        session.commit()
        print(f"Added {len(patients)} random patients to the database.")

if __name__ == "__main__":
    seed_db()
