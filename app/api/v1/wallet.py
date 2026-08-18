"""Study Wallet router — manage time wallet balance, unlock apps, view history."""
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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
    app_package: Optional[str] = None
    package_name: Optional[str] = None
    app_display_name: str = "App"
    unlock_minutes: int = 15

    @property
    def target_package(self) -> str:
        return self.package_name or self.app_package or "com.distraction.app"


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

    return WalletOut(
        wallet_minutes=balance,
        balance_minutes=balance,
        total_earned_minutes=balance,
        transactions=[],
    )


@router.post("/unlock-app", response_model=AppUnlockOut)
async def unlock_app(
    body: AppUnlockIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Spend wallet minutes to temporarily unlock a blocked app."""
    if body.unlock_minutes <= 0 or body.unlock_minutes > 180:
        raise HTTPException(
            status_code=400,
            detail="unlock_minutes must be between 1 and 180 minutes",
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
    minutes: int = Query(10, description="Minutes to add"),
    reason: str = Query("rewarded_ad", description="Reason for addition"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Add minutes to wallet (from rewarded ad or quiz bonus)."""
    if minutes <= 0 or minutes > 180:
        raise HTTPException(status_code=400, detail="minutes must be between 1 and 180")

    current_user.wallet_minutes = (current_user.wallet_minutes or 0) + minutes
    db.commit()

    return WalletOut(
        wallet_minutes=current_user.wallet_minutes,
        balance_minutes=current_user.wallet_minutes,
        total_earned_minutes=current_user.wallet_minutes,
        transactions=[
            WalletTransactionOut(
                description=f"Reward: {reason}",
                minutes_delta=minutes,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        ],
    )
