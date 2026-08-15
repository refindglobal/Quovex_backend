"""
Security utilities: Firebase token verification + JWT for admin dashboard.

Two auth paths:
  1. Mobile App  → Bearer <firebase_id_token>  → verified via Firebase Admin SDK
  2. Admin Dash  → Bearer <jwt_access_token>   → verified via python-jose / SECRET_KEY
"""
import os
from typing import Optional
from functools import lru_cache

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.models import User, AdminRole

security = HTTPBearer(auto_error=False)


# ─── Firebase ─────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_firebase_app():
    """Initialize Firebase Admin SDK once (returns None in dev mode)."""
    if not firebase_admin._apps:
        firebase_json = settings.FIREBASE_SERVICE_ACCOUNT_JSON
        if firebase_json and firebase_json.strip():
            import json as _json
            cred = credentials.Certificate(_json.loads(firebase_json))
            firebase_admin.initialize_app(cred)
        elif os.path.exists(settings.FIREBASE_CREDENTIALS_PATH):
            cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred)
        elif settings.FIREBASE_PROJECT_ID:
            firebase_admin.initialize_app(options={"projectId": settings.FIREBASE_PROJECT_ID})
        else:
            return None  # Dev mode
    return firebase_admin.get_app()


def verify_firebase_token(token: str) -> dict:
    """Verify Firebase ID token. In dev mode (no Firebase config) returns mock payload."""
    app = _get_firebase_app()
    if app is None:
        # Dev mode — mock maps to the seeded admin user
        return {"uid": "admin-seed-uid-000", "email": "admin@quovex.online", "name": "Quovex Admin"}
    try:
        return firebase_auth.verify_id_token(token, app=app)
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Authentication failed: {str(e)}")


def get_or_create_user(db: Session, firebase_uid: str, email: Optional[str], display_name: Optional[str], referral_code: Optional[str] = None) -> User:
    """Get or create a user record from a Firebase or Email identity."""
    from sqlalchemy import func

    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()

    if not user and email:
        email_clean = email.lower().strip()
        user = db.query(User).filter(func.lower(User.email) == email_clean).first()
        if user:
            if not user.firebase_uid or user.firebase_uid.startswith("email:"):
                user.firebase_uid = firebase_uid
                db.commit()
                db.refresh(user)

    if not user:
        email_clean = email.lower().strip() if email else None
        user = User(firebase_uid=firebase_uid, email=email_clean, display_name=display_name)
        if referral_code:
            referrer = db.query(User).filter(User.referral_code == referral_code).first()
            if referrer:
                user.referred_by_id = referrer.id
                user.points_total += 100
        db.add(user)
        db.commit()
        db.refresh(user)
        _ensure_referral_code(user, db)
    return user


def _ensure_referral_code(user: User, db: Session) -> str:
    """Generate a referral code for a user if they don't have one."""
    if not user.referral_code:
        import uuid as _uuid
        user.referral_code = f"USER{_uuid.uuid4().hex[:8].upper()}"
        db.commit()
        db.refresh(user)
    return user.referral_code


# ─── JWT (Admin Dashboard) ────────────────────────────────────────────────────

def _try_jwt_auth(token: str, db: Session) -> Optional[User]:
    """
    Try to decode a JWT token. Returns the User if valid, else None.
    Handles both admin_dashboard and email_auth token types.
    """
    try:
        from app.core.jwt import decode_access_token
        payload = decode_access_token(token)
        user_id_str = payload.get("sub")
        if not user_id_str:
            return None
        try:
            import uuid
            user_id = uuid.UUID(user_id_str)
        except (ValueError, AttributeError):
            return None
        user = db.query(User).filter(User.id == user_id).first()
        if user and not user.is_banned:
            return user
    except Exception:
        pass
    return None


# ─── FastAPI Dependencies ─────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Universal auth dependency.
    Accepts either a Firebase ID token (mobile), an admin JWT (dashboard via header),
    or an admin_token cookie (dashboard via cookie).
    In development mode without token, falls back to local dev user.
    """
    token = None
    if credentials is not None:
        token = credentials.credentials
    elif request.cookies.get("admin_token"):
        token = request.cookies["admin_token"]

    if not token or token.strip() == "" or token in ("null", "undefined"):
        if settings.ENVIRONMENT == "development" or _get_firebase_app() is None:
            return get_or_create_user(db, "admin-seed-uid-000", "admin@quovex.online", "Quovex Admin")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # 1. Try JWT first (fast, no network)
    user = _try_jwt_auth(token, db)
    if user:
        return user

    # 2. Fall back to Firebase token (mobile app)
    payload = verify_firebase_token(token)
    firebase_uid = payload.get("uid")
    email = payload.get("email")
    display_name = payload.get("name")

    user = get_or_create_user(db, firebase_uid, email, display_name)
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is banned")

    return user



async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Requires any admin role (superadmin or support)."""
    if current_user.admin_role not in (AdminRole.superadmin, AdminRole.support):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


async def get_current_superadmin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Requires superadmin role."""
    if current_user.admin_role != AdminRole.superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin access required")
    return current_user
