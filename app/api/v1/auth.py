"""Auth router - handles user registration/profile via Firebase tokens,
and admin dashboard login via email + password (JWT)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from fastapi import Request

from app.core.security import get_current_user, get_current_admin, verify_firebase_token, get_or_create_user
from app.core.jwt import create_access_token
from app.core.constants import SUPPORTED_COUNTRIES, get_filtered_tags, profile_is_complete
from app.db.session import get_db
from app.models import User, AdminRole
from app.schemas import AuthTokenIn, AuthFirebaseIn, AuthOut, UserProfileOut, UserUpdateIn
from app.services.otp_service import generate_otp, verify_otp
from app.services.email_service import send_otp_email
from app.core.limiter import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


# ─── Admin Dashboard Login ────────────────────────────────────────────────────

class AdminLoginIn(BaseModel):
    email: EmailStr
    password: str


class AdminLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfileOut


@router.post("/admin-login", response_model=AdminLoginOut)
@limiter.limit("5/minute")
async def admin_login(body: AdminLoginIn, request: Request, db: Session = Depends(get_db)):
    """
    Email + password login for the admin dashboard.
    Returns a signed JWT (not a Firebase token).
    Only works for users with an admin_role set.
    """
    import bcrypt

    user = db.query(User).filter(func.lower(User.email) == func.lower(body.email)).first()

    if not user or not user.password_hash:
        from app.models import AdminActionLog
        log = AdminActionLog(
            admin_id=None, action="admin_login_failed",
            target_type="admin", target_id=None,
            details=f"Failed login attempt for email: {body.email}",
        )
        db.add(log)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if user.admin_role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access only")

    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is suspended")

    if not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = create_access_token(str(user.id), extra_claims={"role": user.admin_role.value if user.admin_role else None})

    response = JSONResponse(
        content=AdminLoginOut(
            access_token=token,
            user=UserProfileOut.model_validate(user),
        ).model_dump(mode='json'),
    )
    response.set_cookie(
        key="admin_token",
        value=token,
        max_age=28800,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )
    return response


# ─── Admin Change Password ─────────────────────────────────────────────────────

class AdminChangePasswordIn(BaseModel):
    current_password: str
    new_password: str

class AdminChangePasswordOut(BaseModel):
    success: bool
    message: str = "Password changed successfully"


@router.post("/admin-change-password", response_model=AdminChangePasswordOut)
async def admin_change_password(
    body: AdminChangePasswordIn,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Change the authenticated admin user's password."""
    import bcrypt

    if not current_user.password_hash:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No password set for this account")

    if not bcrypt.checkpw(body.current_password.encode(), current_user.password_hash.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    if len(body.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters")

    current_user.password_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    db.commit()

    from app.models import AdminActionLog
    log = AdminActionLog(
        admin_id=current_user.id, action="admin_password_changed",
        target_type="admin", target_id=str(current_user.id),
        details="Admin password changed successfully",
    )
    db.add(log)
    db.commit()

    return AdminChangePasswordOut(success=True)


# ─── Email OTP Login ──────────────────────────────────────────────────────────

class SendOtpIn(BaseModel):
    email: EmailStr

class SendOtpOut(BaseModel):
    success: bool
    message: str

class VerifyOtpIn(BaseModel):
    email: EmailStr
    otp: str
    referral_code: Optional[str] = None

class VerifyOtpOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfileOut


@router.post("/send-otp", response_model=SendOtpOut)
@limiter.limit("5/minute")
async def send_otp(body: SendOtpIn, request: Request, db: Session = Depends(get_db)):
    """Generate and send a 6-digit OTP to the given email."""
    otp = generate_otp(body.email, db=db, ip_address=request.client.host if request.client else None)
    logger.info("=" * 50)
    logger.info(f"🔑 [AUTH OTP] Generated code for {body.email}: {otp}")
    logger.info("=" * 50)
    send_otp_email(body.email, otp)
    return SendOtpOut(
        success=True,
        message="OTP sent to email",
    )


@router.post("/verify-otp", response_model=VerifyOtpOut)
@limiter.limit("5/minute")
async def verify_otp_endpoint(body: VerifyOtpIn, request: Request, db: Session = Depends(get_db)):
    """Verify OTP and return a JWT for the authenticated user."""
    if not verify_otp(body.email, body.otp, db=db):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OTP")

    from app.core.security import get_or_create_user
    firebase_uid = f"email:{body.email}"
    user = get_or_create_user(db, firebase_uid, body.email, body.email.split("@")[0], body.referral_code)

    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is suspended")

    token = create_access_token(str(user.id), token_type="email_auth")

    user.profile_complete = profile_is_complete(user)
    db.commit()
    return VerifyOtpOut(
        access_token=token,
        user=UserProfileOut.model_validate(user),
    )


# ─── Public metadata endpoints ───────────────────────────────────────────────

class SupportedCountryOut(BaseModel):
    countries: list[str]


class CountryExamTagOut(BaseModel):
    tag: str
    category: str
    country: str


@router.get("/supported-countries", response_model=SupportedCountryOut)
async def get_supported_countries():
    """Get list of supported countries for exam tag filtering."""
    return SupportedCountryOut(countries=SUPPORTED_COUNTRIES)


@router.get("/country-exam-tags", response_model=list[CountryExamTagOut])
async def get_country_exam_tags(
    country: str = "",
    education_level: str = "",
):
    """Get exam tags filtered by country and education level."""
    tags = get_filtered_tags(country=country or None, education_level=education_level or None)
    return [CountryExamTagOut(**t) for t in tags]


# ─── Mobile App Login (Firebase) ─────────────────────────────────────────────

@router.post("/login", response_model=AuthOut)
async def login(body: AuthTokenIn, db: Session = Depends(get_db)):
    """
    Verify Firebase token and return the user profile.
    Creates a new user if this is first login.
    """
    payload = verify_firebase_token(body.firebase_token)
    firebase_uid = payload.get("uid")
    email = payload.get("email")
    display_name = payload.get("name")

    user = get_or_create_user(db, firebase_uid, email, display_name, body.referral_code)

    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is suspended")

    if body.device_id and not user.device_id:
        user.device_id = body.device_id
        db.commit()
        db.refresh(user)

    user.profile_complete = profile_is_complete(user)
    db.commit()
    return AuthOut(user=UserProfileOut.model_validate(user))


@router.post("/firebase", response_model=AuthOut)
async def firebase_login(
    body: AuthFirebaseIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Sync Firebase user to backend after Firebase Auth sign-in.
    Used by the Flutter app after Google Sign-In or Email+OTP.
    """
    is_new_user = not current_user.firebase_uid
    if body.display_name and body.display_name != current_user.display_name:
        current_user.display_name = body.display_name
    if body.email and body.email != current_user.email:
        current_user.email = body.email
    if body.avatar_url and body.avatar_url != current_user.avatar_url:
        current_user.avatar_url = body.avatar_url
    if not current_user.firebase_uid and body.firebase_uid:
        current_user.firebase_uid = body.firebase_uid
    if is_new_user and body.referral_code and not current_user.referred_by_id:
        from app.core.security import _ensure_referral_code
        referrer = db.query(User).filter(User.referral_code == body.referral_code).first()
        if referrer and referrer.id != current_user.id:
            current_user.referred_by_id = referrer.id
            current_user.points_total += 100
        _ensure_referral_code(current_user, db)
    db.commit()
    db.refresh(current_user)

    return AuthOut(user=UserProfileOut.model_validate(current_user))
