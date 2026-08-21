"""Referral router — referral codes, stats, bonus claims, and friend redemptions."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.core.security import get_current_user, _ensure_referral_code
from app.db.session import get_db
from app.models import User, SystemSetting
from app.schemas import (
    ReferralStatsOut, ReferralClaimOut, ReferralClaimIn, ReferralGenerateOut,
    ReferralApplyIn, ReferralApplyOut
)
from app.config import settings as app_config

router = APIRouter(prefix="/referral", tags=["referral"])


def _get_referral_config(db: DBSession) -> dict:
    """Retrieve dynamic admin-configurable referral reward settings."""
    setting = db.query(SystemSetting).filter(SystemSetting.key == "referral_rewards").first()
    if setting and isinstance(setting.value, dict):
        return {
            "reward_minutes": int(setting.value.get("reward_minutes_per_referral", 30)),
            "reward_points": int(setting.value.get("reward_points_per_referral", 50)),
            "friend_welcome_minutes": int(setting.value.get("friend_welcome_bonus_minutes", 30)),
            "min_session_minutes": int(setting.value.get("min_session_minutes_to_unlock", 25)),
            "is_active": bool(setting.value.get("is_referral_active", True))
        }
    return {
        "reward_minutes": 30,
        "reward_points": 50,
        "friend_welcome_minutes": 30,
        "min_session_minutes": 25,
        "is_active": True
    }


@router.get("/stats", response_model=ReferralStatsOut)
async def get_referral_stats(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the current user's real referral stats, code, and earnings."""
    _ensure_referral_code(current_user, db)
    cfg = _get_referral_config(db)

    referred_users = (
        db.query(User)
        .filter(User.referred_by_id == current_user.id)
        .all()
    )
    total = len(referred_users)
    pending = sum(1 for u in referred_users if not u.first_session_completed)
    completed_referrals = total - pending
    wallet_mins_earned = completed_referrals * cfg["reward_minutes"]

    referred_by_user = None
    if current_user.referred_by_id:
        referred_by_user = db.query(User).filter(User.id == current_user.referred_by_id).first()

    return ReferralStatsOut(
        referral_code=current_user.referral_code or "",
        total_referred=total,
        bonus_points_earned=current_user.referral_bonus_earned or 0,
        pending_referrals=pending,
        wallet_minutes_earned=wallet_mins_earned,
        reward_minutes_per_referral=cfg["reward_minutes"],
        reward_points_per_referral=cfg["reward_points"],
        has_redeemed_code=current_user.referred_by_id is not None,
        referred_by_name=referred_by_user.display_name if referred_by_user else None
    )


@router.post("/apply", response_model=ReferralApplyOut)
async def apply_referral_code(
    body: ReferralApplyIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Redeem a friend's referral code to claim bonus study wallet minutes."""
    clean_code = body.referral_code.strip().upper()
    if not clean_code:
        raise HTTPException(status_code=400, detail="Please enter a valid referral code")

    if current_user.referred_by_id is not None:
        raise HTTPException(status_code=400, detail="You have already applied a referral code on this account")

    if current_user.referral_code and clean_code == current_user.referral_code.upper():
        raise HTTPException(status_code=400, detail="You cannot use your own referral code")

    referrer = db.query(User).filter(User.referral_code == clean_code).first()
    if not referrer:
        raise HTTPException(status_code=404, detail="Referral code not found. Please check and try again.")

    if referrer.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot refer yourself")

    cfg = _get_referral_config(db)
    welcome_bonus_mins = cfg["friend_welcome_minutes"]

    # Link user to referrer
    current_user.referred_by_id = referrer.id
    current_user.wallet_minutes = (current_user.wallet_minutes or 0) + welcome_bonus_mins

    # If this user already completed their first session, credit referrer now
    if current_user.first_session_completed and not current_user.referral_bonus_paid:
        referrer.referral_bonus_earned = (referrer.referral_bonus_earned or 0) + cfg["reward_points"]
        referrer.wallet_minutes = (referrer.wallet_minutes or 0) + cfg["reward_minutes"]
        referrer.points_total = (referrer.points_total or 0) + cfg["reward_points"]
        current_user.referral_bonus_paid = True

    db.commit()
    db.refresh(current_user)

    return ReferralApplyOut(
        success=True,
        message=f"Success! +{welcome_bonus_mins} minutes added to your Study Wallet.",
        wallet_minutes_awarded=welcome_bonus_mins,
        referrer_name=referrer.display_name or "Friend"
    )


@router.post("/claim", response_model=ReferralClaimOut)
async def claim_referral_bonus(
    body: ReferralClaimIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Claim referral bonus when a referred user completes their first session."""
    referred = db.query(User).filter(User.id == body.referred_user_id).first()
    if not referred:
        raise HTTPException(status_code=404, detail="Referred user not found")
    if referred.referred_by_id != current_user.id:
        raise HTTPException(status_code=400, detail="This user was not referred by you")
    if not referred.first_session_completed:
        raise HTTPException(status_code=400, detail="User has not completed their first session yet")
    if referred.referral_bonus_paid:
        raise HTTPException(status_code=400, detail="Referral bonus already claimed for this user")

    cfg = _get_referral_config(db)
    points = cfg["reward_points"]
    mins = cfg["reward_minutes"]

    current_user.referral_bonus_earned = (current_user.referral_bonus_earned or 0) + points
    current_user.wallet_minutes = (current_user.wallet_minutes or 0) + mins
    current_user.points_total = (current_user.points_total or 0) + points
    referred.referral_bonus_paid = True
    db.commit()
    db.refresh(current_user)
    return ReferralClaimOut(
        points_awarded=points,
        total_bonus=current_user.referral_bonus_earned,
        message=f"You earned +{mins} mins and +{points} bonus points!",
    )


@router.get("/generate-code", response_model=ReferralGenerateOut)
async def generate_referral_code(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Ensure the user has a referral code, generating one if needed."""
    code = _ensure_referral_code(current_user, db)
    return ReferralGenerateOut(referral_code=code)
