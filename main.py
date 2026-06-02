import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from sqlmodel import Session, select

from database import create_db_and_tables, engine
from models import User
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
from routes.bookings import router as bookings_router
from routes.tts import router as tts_router
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


@asynccontextmanager 
async def lifespan(app: FastAPI):
    create_db_and_tables()
    seed_default_admin()
    yield


app = FastAPI(lifespan=lifespan)

allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,   # required for HttpOnly cookie to be sent cross-origin
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(gps_router)
app.include_router(consultation_router) 
app.include_router(patients_router)
app.include_router(clinical_router)
app.include_router(patient_documents_router)
app.include_router(pacs_imaging_router)
app.include_router(operative_notes_router)
app.include_router(clinical_notes_router)
app.include_router(medication_router)
app.include_router(allergy_router)
app.include_router(bookings_router, prefix="/api")
app.include_router(tts_router, prefix="/api")

# Wrap the FastAPI app with the Socket.IO ASGIApp to share the port and host
app = socketio.ASGIApp(sio, other_asgi_app=app)


def main():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
