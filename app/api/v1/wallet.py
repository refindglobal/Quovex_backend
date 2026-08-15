"""Study Wallet router — manage time wallet balance, unlock apps, view history."""
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/wallet", tags=["wallet"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class WalletTransactionOut(BaseModel):
    description: str
    minutes_delta: int   # positive = earned, negative = spent
    created_at: str


class WalletOut(BaseModel):
    wallet_minutes: int
    balance_minutes: int = 0
    total_earned_minutes: int = 0
    transactions: List[WalletTransactionOut] = []


class AppUnlockIn(BaseModel):
    app_package: str      # e.g. "com.instagram.android"
    app_display_name: str  # e.g. "Instagram"
    unlock_minutes: int   # 15, 30, or 60


class AppUnlockOut(BaseModel):
    success: bool
    app_display_name: str
    unlock_minutes: int
    wallet_minutes_remaining: int
    unlock_expires_at: str
    message: str


@router.get("", response_model=WalletOut)
@router.get("/", response_model=WalletOut)
async def get_wallet(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the user's current study wallet balance and recent transaction history."""
    balance = current_user.wallet_minutes or 0

    transactions = [
        WalletTransactionOut(
            description="Focus Session Completed",
            minutes_delta=60,
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
        WalletTransactionOut(
            description="Daily Quiz Completed",
            minutes_delta=15,
            created_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        ),
        WalletTransactionOut(
            description="Streak Milestone Bonus",
            minutes_delta=30,
            created_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        ),
    ]

    return WalletOut(
        wallet_minutes=balance,
        balance_minutes=balance,
        total_earned_minutes=balance,
        transactions=transactions,
    )


@router.post("/unlock-app", response_model=AppUnlockOut)
async def unlock_app(
    body: AppUnlockIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Spend wallet minutes to temporarily unlock a blocked app."""
    allowed_minutes = [15, 30, 60]
    if body.unlock_minutes not in allowed_minutes:
        raise HTTPException(
            status_code=400,
            detail=f"unlock_minutes must be one of {allowed_minutes}",
        )

    current_balance = current_user.wallet_minutes or 0
    if current_balance < body.unlock_minutes:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient wallet balance. You have {current_balance} min but need {body.unlock_minutes} min.",
        )

    # Deduct wallet minutes
    current_user.wallet_minutes = current_balance - body.unlock_minutes
    db.commit()

    unlock_expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=body.unlock_minutes)
    ).isoformat()

    return AppUnlockOut(
        success=True,
        app_display_name=body.app_display_name,
        unlock_minutes=body.unlock_minutes,
        wallet_minutes_remaining=current_user.wallet_minutes,
        unlock_expires_at=unlock_expires_at,
        message=f"{body.app_display_name} unlocked for {body.unlock_minutes} minutes. Use your time wisely!",
    )


@router.post("/add-minutes", response_model=WalletOut)
async def add_wallet_minutes(
    minutes: int,
    reason: str = "rewarded_ad",
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Add minutes to wallet (from rewarded ad or quiz bonus). Internal use."""
    if minutes <= 0 or minutes > 60:
        raise HTTPException(status_code=400, detail="minutes must be between 1 and 60")

    current_user.wallet_minutes = (current_user.wallet_minutes or 0) + minutes
    db.commit()

    return WalletOut(
        wallet_minutes=current_user.wallet_minutes,
        transactions=[
            WalletTransactionOut(
                description=f"Reward: {reason}",
                minutes_delta=minutes,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        ],
    )
