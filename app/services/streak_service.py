"""
Streak Service — Accurate, timezone-aware daily streak calculations and streak protection.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from sqlalchemy.orm import Session as DBSession

from app.models import User


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def calculate_effective_streak(user: User, now: Optional[datetime] = None) -> Tuple[int, bool, bool]:
    """
    Calculate the user's active streak in real-time.
    
    Returns:
        (effective_streak_count, is_frozen_active, studied_today)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = _ensure_utc(now)

    today = now.date()
    
    # Check if streak freeze is active right now
    frozen_until = _ensure_utc(user.streak_frozen_until)
    is_frozen_active = bool(frozen_until and frozen_until > now)

    last_study = _ensure_utc(user.last_study_date)
    if not last_study:
        return 0, is_frozen_active, False

    last_date = last_study.date()
    days_since = (today - last_date).days

    if days_since < 0:
        # Future study date anomaly -> treat as studied today
        return user.streak_count or 1, is_frozen_active, True

    if days_since == 0:
        # Studied today -> active streak is current count
        return max(1, user.streak_count or 1), is_frozen_active, True

    if days_since == 1:
        # Studied yesterday, haven't studied today yet -> streak is alive (at risk)
        return max(1, user.streak_count or 1), is_frozen_active, False

    # Missed 1 or more full days (days_since >= 2)
    # Check if freeze covered the missed gap
    if is_frozen_active:
        # Protected by active streak freeze
        return max(1, user.streak_count or 1), True, False

    # Check if freeze was active during the missed day
    if frozen_until and frozen_until.date() >= (today - timedelta(days=1)):
        return max(1, user.streak_count or 1), False, False

    # Streak has lapsed
    return 0, False, False


def update_streak_on_session_complete(user: User, verified_minutes: int, now: Optional[datetime] = None) -> int:
    """
    Update streak count upon completing a verified study session.
    
    Returns:
        new_streak_count
    """
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = _ensure_utc(now)

    today = now.date()
    last_study = _ensure_utc(user.last_study_date)
    frozen_until = _ensure_utc(user.streak_frozen_until)
    is_frozen = bool(frozen_until and frozen_until >= now - timedelta(hours=24))

    if not last_study or not user.streak_count or user.streak_count <= 0:
        # First ever study session or starting from 0
        user.streak_count = 1
    else:
        last_date = last_study.date()
        days_since = (today - last_date).days

        if days_since <= 0:
            # Already studied today -> maintain current streak count
            pass
        elif days_since == 1:
            # Consecutive day study -> increment streak!
            user.streak_count += 1
        elif days_since == 2 and (is_frozen or (frozen_until and frozen_until.date() >= (today - timedelta(days=1)))):
            # Missed exactly 1 day, but streak freeze protected that day -> increment streak!
            user.streak_count += 1
        else:
            # Streak was broken without valid protection -> reset to 1 for today's session
            user.streak_count = 1

    user.last_study_date = now
    return user.streak_count
