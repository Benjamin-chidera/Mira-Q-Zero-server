import os
import re
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlmodel import Session, select
from pydantic import BaseModel, field_validator
from models import User
from database import get_session
from utils.jwt_handler import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "access_token"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "80"))

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── Request / Response schemas ────────────────────────────────────────────────

class CheckEmailRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v


class CheckEmailResponse(BaseModel):
    exists: bool
    name: str | None = None
    has_password: bool = False


class SetPasswordRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v



class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v


class RegisterRequest(BaseModel):
    email: str
    name: str
    role: str = "practitioner"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("admin", "practitioner"):
            raise ValueError("Role must be 'admin' or 'practitioner'")
        return v


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str


class LoginResponse(BaseModel):
    user: UserOut
    # access_token is also returned here so Swagger UI can use it via
    # the Authorize button (Bearer scheme). The browser frontend ignores
    # this field and relies solely on the HttpOnly cookie.
    access_token: str


# ── Auth dependency ───────────────────────────────────────────────────────────

def get_current_user(request: Request, db: Session = Depends(get_session)) -> User:
    # 1. Try the HttpOnly cookie (browser clients)
    token = request.cookies.get(COOKIE_NAME)

    # 2. Fall back to Authorization: Bearer <token> (Swagger / API clients)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, response: Response, db: Session = Depends(get_session)):
    user = db.exec(
        select(User).where(User.email == data.email, User.is_active == True)
    ).first()

    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(user.id, user.role)

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=EXPIRE_HOURS * 3600,
        path="/",
    )

    return LoginResponse(
        access_token=token,
        user=UserOut(id=user.id, email=user.email, name=user.name, role=user.role),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")


@router.post("/admin/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_employee(
    data: RegisterRequest,
    db: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    existing = db.exec(select(User).where(User.email == data.email)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email '{data.email}' already exists",
        )

    new_user = User(
        email=data.email,
        name=data.name,
        role=data.role,
        # password_hash is omitted, defaults to None
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return UserOut(id=new_user.id, email=new_user.email, name=new_user.name, role=new_user.role)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        role=current_user.role,
    )


@router.post("/check-email", response_model=CheckEmailResponse)
def check_email(data: CheckEmailRequest, db: Session = Depends(get_session)):
    user = db.exec(
        select(User).where(User.email == data.email, User.is_active == True)
    ).first()

    if not user:
        return CheckEmailResponse(exists=False)

    return CheckEmailResponse(
        exists=True,
        name=user.name,
        has_password=bool(user.password_hash)
    )


@router.post("/set-password", response_model=LoginResponse)
def set_password(data: SetPasswordRequest, response: Response, db: Session = Depends(get_session)):
    user = db.exec(
        select(User).where(User.email == data.email, User.is_active == True)
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is already set. Please log in.",
        )

    user.password_hash = hash_password(data.password)
    db.add(user)
    db.commit()

    token = create_access_token(user.id, user.role)

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=EXPIRE_HOURS * 3600,
        path="/",
    )

    return LoginResponse(
        access_token=token,
        user=UserOut(id=user.id, email=user.email, name=user.name, role=user.role),
    )
