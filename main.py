import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from sqlmodel import Session, select

from database import create_db_and_tables, engine
from models import User
from utils.mira.ai_research_models import ResearchConversation, ResearchMessage
from utils.jwt_handler import hash_password
from routes.gps import router as gps_router
from routes.consultation import router as consultation_router
from routes.auth import router as auth_router
from routes.mira.patients import router as patients_router
from routes.mira.clinical import router as clinical_router
from routes.mira.patient_documents import router as patient_documents_router
from routes.mira.pacs_imaging import router as pacs_imaging_router
from routes.mira.operative_notes import router as operative_notes_router
from routes.mira.clinical_notes import router as clinical_notes_router
from routes.mira.medication import router as medication_router
from routes.mira.allergy import router as allergy_router
from routes.mira.notifications import router as notifications_router
from routes.bookings import router as bookings_router
from routes.tts import router as tts_router
from routes.mira.ai_research import router as ai_research_router
from routes.mira.research_center_route import router as research_center_router
from routes.mira.case_history_route import router as case_history_router
from utils.mira.case_history.history import CaseHistory
import socketio
from socket_setup import sio

load_dotenv()


def seed_default_admin():
    admin_email = os.getenv("ADMIN_EMAIL", "admin@gpconnect.nhs.uk")
    admin_password = os.getenv("ADMIN_PASSWORD", "AdminPass123!")
    admin_name = os.getenv("ADMIN_NAME", "System Administrator")

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.email == admin_email)).first()
        if not existing:
            admin = User(
                email=admin_email,
                password_hash=hash_password(admin_password),
                name=admin_name,
                role="admin",
            )
            session.add(admin)
            session.commit()
            print(f"[Seed] Default admin created: {admin_email}")
        else:
            print(f"[Seed] Admin already exists: {admin_email}")


def seed_default_doctors():
    doctors_data = [
        {"email": "benjaminchidera72@gmail.com", "name": "Benjamin Chidera", "password": "Standout070801?"},
        {"email": "house@gpconnect.nhs.uk", "name": "Gregory House", "password": "Password123!"},
        {"email": "grey@gpconnect.nhs.uk", "name": "Meredith Grey", "password": "Password123!"},
        {"email": "quinn@gpconnect.nhs.uk", "name": "Michaela Quinn", "password": "Password123!"},
        {"email": "mccoy@gpconnect.nhs.uk", "name": "Leonard McCoy", "password": "Password123!"},
    ]
    with Session(engine) as session:
        for doc in doctors_data:
            existing = session.exec(select(User).where(User.email == doc["email"])).first()
            if not existing:
                practitioner = User(
                    email=doc["email"],
                    password_hash=hash_password(doc["password"]),
                    name=doc["name"],
                    role="practitioner",
                )
                session.add(practitioner)
            else:
                existing.name = doc["name"]
                existing.password_hash = hash_password(doc["password"])
                session.add(existing)
        session.commit()
        print("[Seed] Practitioners seeded successfully.")


@asynccontextmanager 
async def lifespan(app: FastAPI):
    create_db_and_tables()
    
    # Run auto-migration for doctor_id column
    from sqlalchemy import text
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE patient ADD COLUMN doctor_id INTEGER"))
            print("[Migration] Added doctor_id to patient table.")
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE researchconversation ADD COLUMN status VARCHAR DEFAULT 'Ongoing'"))
            print("[Migration] Added status to researchconversation table.")
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE researchconversation ADD COLUMN status_reason VARCHAR"))
            print("[Migration] Added status_reason to researchconversation table.")
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE researchmessage MODIFY COLUMN content LONGTEXT"))
            print("[Migration] Altered researchmessage content column to LONGTEXT.")
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE researchmessage MODIFY COLUMN attachments_json LONGTEXT"))
            print("[Migration] Altered researchmessage attachments_json column to LONGTEXT.")
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE researchmessage MODIFY COLUMN sources_json LONGTEXT"))
            print("[Migration] Altered researchmessage sources_json column to LONGTEXT.")
        except Exception:
            pass
            
    seed_default_admin()
    seed_default_doctors()
    yield


app = FastAPI(lifespan=lifespan)

@app.get("/")
def root():
    return {"message": "Welcome to GP Connect"}


@app.get("/health")
def health_check():
    # Dokploy uses this endpoint to verify the container is healthy.
    # A 200 response keeps the deployment; a failure triggers a rollback.
    return {"status": "ok"}
 
allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):\d+",
    allow_credentials=True,   # required for HttpOnly cookie to be sent cross-origin
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers both with and without /api prefix to support all client configurations
routers = [
    (auth_router, ""),
    (gps_router, ""),
    (consultation_router, ""),
    (patients_router, ""),
    (clinical_router, ""),
    (patient_documents_router, ""),
    (pacs_imaging_router, ""),
    (operative_notes_router, ""),
    (clinical_notes_router, ""),
    (medication_router, ""),
    (allergy_router, ""),
    (notifications_router, ""),
    (bookings_router, "/api"),
    (tts_router, "/api"),
    (ai_research_router, ""),
    (research_center_router, ""),
    (case_history_router, ""),
]

for r, default_prefix in routers:
    if default_prefix == "/api":
        app.include_router(r, prefix="/api")
        app.include_router(r)
    else:
        app.include_router(r)
        app.include_router(r, prefix="/api")

# Wrap the FastAPI app with the Socket.IO ASGIApp to share the port and host
app = socketio.ASGIApp(sio, other_asgi_app=app)


def main():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
