"""Sessions router - start/end study sessions, ad doubling, social unlock."""
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.core.security import get_current_user
from app.core.anti_cheat import compute_anti_cheat_score, should_flag
from app.db.session import get_db
from app.models import User, Session as StudySession, StudyMode
from app.schemas import (
    SessionStartIn, SessionStartOut,
    SessionEndIn, SessionEndOut, BadgeOut,
    SessionAdDoubleIn, SessionAdDoubleOut,
    SessionPauseOut, SessionResumeOut, SessionHeartbeatIn, SessionHeartbeatOut,
    SessionOut,
)
from app.services.points_service import (
    calculate_points, apply_ad_double, get_daily_verified_minutes
)
from app.services.badge_service import check_and_award_badges
from app.services.notification_service import send_rank_change
from app.services.leaderboard_service import get_user_rank


def _notify_rank_changes(db, user, tracks):
    for track in tracks:
        rank_data = get_user_rank(db, user.id, track, "global", "month")
        if not rank_data:
            continue
        new_rank = rank_data["rank"]
        last_ranks = user.last_known_ranks or {}
        old_rank = last_ranks.get(track)
        if old_rank is not None and old_rank != new_rank:
            send_rank_change(db, user, old_rank, new_rank, track)
        last_ranks[track] = new_rank
        user.last_known_ranks = last_ranks
    db.commit()


router = APIRouter(prefix="/sessions", tags=["sessions"])

from app.config import settings as app_config
SOCIAL_UNLOCK_PER_HOUR = app_config.SOCIAL_UNLOCK_MINUTES_PER_HOUR
SOCIAL_UNLOCK_AD_BONUS = app_config.SOCIAL_UNLOCK_AD_BONUS_MINUTES
SOCIAL_UNLOCK_AD_COOLDOWN_HRS = app_config.SOCIAL_UNLOCK_AD_COOLDOWN_HOURS

from pydantic import BaseModel

class TodaySessionSummaryOut(BaseModel):
    total_minutes_today: int
    target_minutes: int
    sessions_count: int
    xp_today: int

@router.get("/today", response_model=TodaySessionSummaryOut)
async def get_today_session(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get today's total focus minutes, goal target, session count, and XP."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    sessions = db.query(StudySession).filter(
        StudySession.user_id == current_user.id,
        StudySession.start_time >= today_start,
        StudySession.is_active == False
    ).all()

    total_mins = sum(s.verified_minutes for s in sessions)
    xp_today = sum(s.points_awarded for s in sessions)
    target_mins = int(current_user.daily_target_hours * 60) if current_user.daily_target_hours else (current_user.daily_study_target_minutes or 240)

    return TodaySessionSummaryOut(
        total_minutes_today=total_mins,
        target_minutes=target_mins,
        sessions_count=len(sessions),
        xp_today=xp_today
    )


@router.post("/start", response_model=SessionStartOut)
async def start_session(
    body: SessionStartIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Start a new study session. Ends any existing active session first."""
    # End any lingering active session
    active = (
        db.query(StudySession)
        .filter(StudySession.user_id == current_user.id, StudySession.is_active == True)
        .first()
    )
    if active:
        active.is_active = False
        active.end_time = datetime.now(timezone.utc)
        db.commit()

    # Re-enable app lock for the new session (if user has a daily target)
    if current_user.daily_study_target_minutes and current_user.daily_study_target_minutes > 0:
        current_user.app_lock_enabled = True

    # Normalize mode string to StudyMode enum
    raw_mode = (body.mode or "focus").lower()
    if raw_mode in ["mode_a", "offline", "strict"]:
        study_mode = StudyMode.offline
    elif raw_mode in ["mode_b", "online", "digital"]:
        study_mode = StudyMode.online
    elif raw_mode in ["mode_c", "focus", "youtube"]:
        study_mode = StudyMode.focus
    elif raw_mode in ["mode_d", "pomodoro"]:
        study_mode = StudyMode.pomodoro
    elif raw_mode in ["exam"]:
        study_mode = StudyMode.exam
    else:
        study_mode = StudyMode.focus

    session = StudySession(
        user_id=current_user.id,
        mode=study_mode,
        start_time=datetime.now(timezone.utc),
        subject_tag=body.subject_tag,
        exam_tag=body.exam_tag,
        topic_id=body.topic_id,
        locked_app_count=len(body.locked_apps or []),
        whitelist_apps=body.whitelist_apps or [],
        is_active=True,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return SessionStartOut(
        session_id=session.id,
        started_at=session.start_time,
        mode=session.mode.value if hasattr(session.mode, "value") else str(session.mode),
    )


@router.post("/{session_id}/end", response_model=SessionEndOut)
async def end_session_by_id(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """End a session by its ID in the URL path (Flutter uses this pattern)."""
    from app.schemas import SessionEndIn
    body = SessionEndIn(session_id=session_id)
    return await end_session(body, current_user, db)


@router.post("/end", response_model=SessionEndOut)
async def end_session(
    body: SessionEndIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """End a study session: calculate verified minutes, points, streak, anti-cheat."""
    session = (
        db.query(StudySession)
        .filter(
            StudySession.id == body.session_id,
            StudySession.user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.is_active:
        raise HTTPException(status_code=400, detail="Session already ended")

    now = datetime.now(timezone.utc)
    session.end_time = now
    session.is_active = False
    if body.honor_check_failures is not None:
        session.honor_check_failures = body.honor_check_failures

    # Calculate raw minutes (exclude paused time)
    st = session.start_time if (session.start_time and session.start_time.tzinfo) else session.start_time.replace(tzinfo=timezone.utc)
    elapsed_seconds = int((now - st).total_seconds()) - (session.total_paused_seconds or 0)
    raw_minutes = max(0, elapsed_seconds // 60)
    session.raw_minutes = raw_minutes

    # Verified = raw for offline; online has additional checks (placeholder for Phase 2)
    verified_minutes = raw_minutes
    session.verified_minutes = verified_minutes

    # Anti-cheat check
    daily_so_far = get_daily_verified_minutes(current_user.id, db)
    anti_cheat_score, flag_reason = compute_anti_cheat_score(
        db, current_user.id, session, daily_so_far
    )
    session.anti_cheat_score = anti_cheat_score
    if should_flag(anti_cheat_score):
        session.flagged = True
        session.flag_reason = flag_reason
        # Flagged sessions don't award full points/minutes to leaderboard
        verified_minutes = 0

    # Calculate points
    points = calculate_points(verified_minutes, daily_so_far)
    session.points_base = points
    session.points_awarded = points

    # Update user totals
    current_user.verified_minutes_total += verified_minutes
    current_user.points_total += points

    # Update streak
    _update_streak(current_user, now)

    # First session completed (for referral bonus)
    if verified_minutes > 0 and not current_user.first_session_completed:
        current_user.first_session_completed = True
        _auto_claim_referral(current_user, db)

    # Social unlock time earned
    social_earned = (verified_minutes // 60) * SOCIAL_UNLOCK_PER_HOUR
    _add_social_unlock(current_user, social_earned, now)

    # App lock credits earned (15 per verified hour, max 90)
    from app.config import settings as app_settings
    app_lock_earned = (verified_minutes // 60) * app_settings.APP_LOCK_CREDITS_PER_HOUR
    if app_lock_earned > 0:
        current_user.app_lock_credits = min(
            current_user.app_lock_credits + app_lock_earned,
            app_settings.APP_LOCK_MAX_CREDITS,
        )

    # Study Wallet credit: 15 minutes per verified study hour (PRD §4.2)
    # Formula: earned_wallet_minutes = floor(verified_minutes / 60) * 15
    wallet_minutes_earned = (verified_minutes // 60) * 15
    if wallet_minutes_earned > 0:
        current_user.wallet_minutes = (current_user.wallet_minutes or 0) + wallet_minutes_earned

    # Daily target → auto-unlock
    daily_target_met = False
    if current_user.daily_study_target_minutes and current_user.daily_study_target_minutes > 0:
        today_minutes = get_daily_verified_minutes(current_user.id, db)
        if today_minutes >= current_user.daily_study_target_minutes:
            current_user.app_lock_enabled = False
            daily_target_met = True
            from app.services.notification_service import send_notification
            try:
                send_notification(db, current_user, "Daily Goal Reached!",
                    f"Amazing! You hit your {current_user.daily_study_target_minutes}min study target today. Keep the streak alive!",
                    "daily_target_met")
            except Exception:
                pass

    # Ad double availability
    ad_doubles_available = current_user.ad_doubles_used_today < app_config.MAX_DAILY_AD_DOUBLES

    db.commit()
    db.refresh(session)
    db.refresh(current_user)

    new_badges = check_and_award_badges(current_user, db)

    if verified_minutes > 0:
        _notify_rank_changes(db, current_user, ["study", "overall"])

    return SessionEndOut(
        session_id=session.id,
        verified_minutes=verified_minutes,
        points_awarded=points,
        points_base=points,
        streak_count=current_user.streak_count,
        ad_double_available=ad_doubles_available and not session.flagged,
        social_unlock_minutes_earned=social_earned,
        wallet_minutes_earned=wallet_minutes_earned,
        flagged=session.flagged,
        message="Great session! Keep up the focus." if not session.flagged else "Session flagged for review.",
        new_badges=new_badges,
        daily_target_met=daily_target_met,
    )


@router.post("/{session_id}/ad-double", response_model=SessionAdDoubleOut)
async def ad_double_session_by_id(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Apply 2x points multiplier by session ID in URL path."""
    body = SessionAdDoubleIn(session_id=session_id)
    return await ad_double_session(body, current_user, db)


@router.post("/ad-double", response_model=SessionAdDoubleOut)
async def ad_double_session(
    body: SessionAdDoubleIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Apply 2x points multiplier after watching a rewarded ad (max 2/day)."""
    session = (
        db.query(StudySession)
        .filter(
            StudySession.id == body.session_id,
            StudySession.user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.flagged:
        raise HTTPException(status_code=400, detail="Cannot double points on a flagged session")

    new_points, success = apply_ad_double(current_user, session, db)
    return SessionAdDoubleOut(
        points_awarded=new_points,
        success=success,
        message="Points doubled!" if success else "Daily ad limit reached (max 2/day)",
    )


@router.post("/ad-extend")
async def ad_extend_session(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Extend the current active session by +15 verified minutes after watching a rewarded ad."""
    session = (
        db.query(StudySession)
        .filter(
            StudySession.user_id == current_user.id,
            StudySession.is_active == True,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=400, detail="No active session to extend")
    EXTRA_MINUTES = app_config.AD_EXTEND_MINUTES
    EXTRA_POINTS = app_config.AD_EXTEND_POINTS
    session.verified_minutes += EXTRA_MINUTES
    session.points_awarded += EXTRA_POINTS
    session.points_base += EXTRA_POINTS
    current_user.verified_minutes_total += EXTRA_MINUTES
    current_user.points_total += EXTRA_POINTS
    db.commit()
    return {
        "status": "ok",
        "extra_minutes": EXTRA_MINUTES,
        "extra_points": EXTRA_POINTS,
        "verified_minutes_total": session.verified_minutes,
        "message": f"Session extended by {EXTRA_MINUTES} minutes!",
    }


@router.post("/ad-continue")
async def ad_continue_session(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Allow user to continue an active session after watching a rewarded ad on honor check."""
    session = (
        db.query(StudySession)
        .filter(
            StudySession.user_id == current_user.id,
            StudySession.is_active == True,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=400, detail="No active session to continue")
    session.honor_check_failures = 0
    db.commit()
    return {
        "status": "ok",
        "message": "Session continued \u2014 honor check failures reset",
    }


@router.post("/{session_id}/pause", response_model=SessionPauseOut)
async def pause_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Pause an active session (user manually paused or app backgrounded)."""
    session = (
        db.query(StudySession)
        .filter(
            StudySession.id == session_id,
            StudySession.user_id == current_user.id,
            StudySession.is_active == True,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found")
    now = datetime.now(timezone.utc)
    session.is_paused = True
    session.paused_at = now
    db.commit()
    return SessionPauseOut(status="paused", paused_at=now)


@router.post("/{session_id}/resume", response_model=SessionResumeOut)
async def resume_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Resume a paused session."""
    session = (
        db.query(StudySession)
        .filter(
            StudySession.id == session_id,
            StudySession.user_id == current_user.id,
            StudySession.is_active == True,
            StudySession.is_paused == True,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Paused session not found")
    now = datetime.now(timezone.utc)
    if session.paused_at:
        paused_secs = int((now - session.paused_at).total_seconds())
        session.total_paused_seconds += paused_secs
    session.is_paused = False
    session.paused_at = None
    db.commit()
    return SessionResumeOut(status="resumed", resumed_at=now)


@router.post("/{session_id}/heartbeat", response_model=SessionHeartbeatOut)
async def session_heartbeat(
    session_id: UUID,
    body: SessionHeartbeatIn = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Heartbeat to keep session alive and record liveness checks."""
    session = (
        db.query(StudySession)
        .filter(
            StudySession.id == session_id,
            StudySession.user_id == current_user.id,
            StudySession.is_active == True,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found")

    if body:
        if body.liveness_passed is False:
            session.honor_check_failures = (session.honor_check_failures or 0) + 1
        if body.app_violation_count is not None and hasattr(session, "distraction_count"):
            session.distraction_count = body.app_violation_count
        db.commit()

    now = datetime.now(timezone.utc)
    st = session.start_time if (session.start_time and session.start_time.tzinfo) else session.start_time.replace(tzinfo=timezone.utc)
    elapsed = int((now - st).total_seconds()) - (session.total_paused_seconds or 0)
    return SessionHeartbeatOut(status="ok", elapsed_seconds=max(0, elapsed))


@router.get("/history", response_model=list[SessionOut])
async def get_session_history(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the current user's session history."""
    sessions = (
        db.query(StudySession)
        .filter(
            StudySession.user_id == current_user.id,
            StudySession.is_active == False,
        )
        .order_by(StudySession.start_time.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [SessionOut.model_validate(s) for s in sessions]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _update_streak(user: User, now: datetime):
    today = now.date()
    if user.last_study_date:
        last = user.last_study_date.date()
        if last == today:
            pass  # Already studied today
        elif last == today - timedelta(days=1):
            user.streak_count += 1
        else:
            user.streak_count = 1  # Streak broken
    else:
        user.streak_count = 1
    user.last_study_date = now


def _auto_claim_referral(user: User, db: DBSession):
    """Auto-claim referral bonus for the referrer when referred user completes first session."""
    if not user.referred_by_id:
        return
    if user.referral_bonus_paid:
        return
    referrer = db.query(User).filter(User.id == user.referred_by_id).first()
    if not referrer:
        return
    REFERRAL_BONUS = 50
    referrer.referral_bonus_earned += REFERRAL_BONUS
    referrer.points_total += REFERRAL_BONUS
    user.referral_bonus_paid = True
    db.commit()
