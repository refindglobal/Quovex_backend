"""Admin router - user management, anti-cheat review, rewards, analytics."""
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func, desc
from pydantic import BaseModel

from app.core.security import get_current_admin, get_current_superadmin
import uuid as uuid_lib
from app.db.session import get_db
from app.db.redis_client import get_redis
from app.models import (
    User, Session as StudySession, QuizQuestion, QuizSession, Reward, AdminActionLog,
    AdRevenueLog, OTPLog, RewardStatus, RewardType, QuestionStatus, AdminRole,
    LeaderboardSnapshot, LeaderboardTrack, LeaderboardPeriod, LeaderboardScope, NotificationLog,
    GradeSubject, SystemSetting,
)
from app.schemas import (
    AdminUserListOut, AdminUserDetailOut, AdminUserUpdateIn,
    AdminSessionFlagOut, AdminSessionActionIn, AdminOverviewOut,
    QuizQuestionAdminOut, QuizQuestionUpdateIn,
    RewardOut, PaginatedOut, NotificationComposePush,
    AdminReferralSettingsOut, AdminReferralSettingsIn,
    SupportTicketListOut, SupportTicketOut, SupportTicketUpdateIn,
)
from app.api.v1.rewards import RewardDetailOut
from app.services.analytics_service import get_geo_breakdown, get_divergence_analysis
from app.services.notification_service import broadcast_notification
from app.tasks.monthly_leaderboard_freeze import freeze_leaderboard
from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


# ─── Overview ────────────────────────────────────────────────────────────────

@router.get("/overview", response_model=AdminOverviewOut)
async def get_overview(
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """KPI cards for dashboard home."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    thirty_days = now - timedelta(days=30)

    dau = db.query(func.count(func.distinct(StudySession.user_id))).filter(
        StudySession.start_time >= today_start
    ).scalar() or 0

    mau = db.query(func.count(func.distinct(StudySession.user_id))).filter(
        StudySession.start_time >= thirty_days
    ).scalar() or 0

    sessions_today = db.query(func.count(StudySession.id)).filter(
        StudySession.start_time >= today_start
    ).scalar() or 0

    verified_today = db.query(func.sum(StudySession.verified_minutes)).filter(
        StudySession.start_time >= today_start,
        StudySession.is_active == False,
    ).scalar() or 0

    total_users = db.query(func.count(User.id)).scalar() or 0
    active_sessions = db.query(func.count(StudySession.id)).filter(
        StudySession.is_active == True
    ).scalar() or 0

    active_groups = db.query(func.count(func.distinct(User.id))).filter(
        User.institution_type.isnot(None)
    ).scalar() or 0

    avg_focus = db.query(func.avg(StudySession.verified_minutes)).filter(
        StudySession.start_time >= thirty_days
    ).scalar() or 0

    quizzes_completed = db.query(func.count(QuizSession.id)).filter(
        QuizSession.is_complete == True,
        QuizSession.start_time >= month_start,
    ).scalar() or 0

    anti_cheat_flags = db.query(func.count(StudySession.id)).filter(
        StudySession.flagged == True
    ).scalar() or 0

    premium_subscribers = db.query(func.count(User.id)).filter(
        User.admin_role.isnot(None)
    ).scalar() or 0

    return AdminOverviewOut(
        dau=dau, mau=mau, sessions_today=sessions_today,
        verified_minutes_today=verified_today,
        total_users=total_users, active_sessions=active_sessions,
        active_groups=active_groups,
        avg_focus_time_minutes=round(float(avg_focus), 1),
        quizzes_completed=quizzes_completed,
        anti_cheat_flags=anti_cheat_flags,
        premium_subscribers=premium_subscribers,
    )


# ─── Users ───────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[AdminUserListOut])
async def list_users(
    search: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    exam_tag: Optional[str] = Query(None),
    is_banned: Optional[bool] = Query(None),
    flagged: Optional[bool] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    query = db.query(User)
    if search:
        query = query.filter(
            (User.display_name.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%"))
        )
    if country:
        query = query.filter(User.country == country)
    if is_banned is not None:
        query = query.filter(User.is_banned == is_banned)
    if exam_tag:
        query = query.filter(User.exam_tags.contains([exam_tag]))
    query = query.order_by(desc(User.created_at)).limit(limit).offset(offset)
    return [AdminUserListOut.model_validate(u) for u in query.all()]


@router.get("/users/{user_id}", response_model=AdminUserDetailOut)
async def get_user_detail(
    user_id: UUID,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    sessions = (
        db.query(StudySession)
        .filter(StudySession.user_id == user_id)
        .order_by(desc(StudySession.start_time))
        .limit(20)
        .all()
    )
    from app.schemas import SessionOut
    data = AdminUserDetailOut.model_validate(user)
    data.sessions = [SessionOut.model_validate(s) for s in sessions]
    return data


@router.patch("/users/{user_id}", response_model=AdminUserListOut)
async def update_user(
    user_id: UUID,
    body: AdminUserUpdateIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.is_banned is not None:
        user.is_banned = body.is_banned
        user.ban_reason = body.ban_reason

    if body.admin_role is not None:
        # Only superadmin can change roles
        if admin.admin_role != AdminRole.superadmin:
            raise HTTPException(status_code=403, detail="Superadmin required to change roles")
        user.admin_role = body.admin_role

    if body.points_adjustment is not None:
        user.points_total += body.points_adjustment
        log = AdminActionLog(
            admin_id=admin.id,
            action_type="points_adjustment",
            target_user_id=user_id,
            notes=body.adjustment_reason,
            # BUG FIX: column is named action_metadata, not metadata
            action_metadata={"adjustment": body.points_adjustment},
        )
        db.add(log)

    if body.daily_study_target_minutes is not None:
        user.daily_study_target_minutes = body.daily_study_target_minutes

    db.commit()
    db.refresh(user)
    return AdminUserListOut.model_validate(user)


# ─── Anti-Cheat ──────────────────────────────────────────────────────────────

@router.get("/anti-cheat/flagged", response_model=list[AdminSessionFlagOut])
async def get_flagged_sessions(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    sessions = (
        db.query(StudySession)
        .filter(StudySession.flagged == True)
        .order_by(desc(StudySession.start_time))
        .limit(limit).offset(offset)
        .all()
    )
    result = []
    for s in sessions:
        user = db.query(User).filter(User.id == s.user_id).first()
        out = AdminSessionFlagOut.model_validate(s)
        out.user_name = user.display_name if user else None
        result.append(out)
    return result


@router.post("/anti-cheat/sessions/{session_id}/action")
async def action_flagged_session(
    session_id: UUID,
    body: AdminSessionActionIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    session = db.query(StudySession).filter(StudySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if body.action == "approve":
        session.flagged = False
        # Restore points/minutes
        session.verified_minutes = session.raw_minutes
        user = db.query(User).filter(User.id == session.user_id).first()
        if user:
            user.verified_minutes_total += session.verified_minutes
    elif body.action == "reject":
        session.verified_minutes = 0
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    log = AdminActionLog(
        admin_id=admin.id,
        action_type=f"session_{body.action}",
        target_user_id=session.user_id,
        target_resource_type="session",
        target_resource_id=str(session_id),
        notes=body.notes,
    )
    db.add(log)
    db.commit()
    return {"status": "ok", "action": body.action}


# ─── Quiz Question Library (all auto-live, no review queue) ──────────────────

@router.get("/quiz/questions", response_model=list[QuizQuestionAdminOut])
async def list_questions(
    status: Optional[str] = Query("live"),  # all questions are live by default
    subject: Optional[str] = Query(None),
    exam_tag: Optional[str] = Query(None),
    grade_or_tag: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """List quiz questions. All generated questions are live — no review queue."""
    query = db.query(QuizQuestion)
    if status:
        try:
            query = query.filter(QuizQuestion.status == QuestionStatus[status])
        except KeyError:
            pass
    if subject:
        query = query.filter(QuizQuestion.subject == subject)
    if exam_tag:
        query = query.filter(QuizQuestion.exam_tag == exam_tag)
    if grade_or_tag:
        query = query.filter(QuizQuestion.grade_or_tag == grade_or_tag)
    if difficulty:
        query = query.filter(QuizQuestion.difficulty == difficulty)
    if search:
        query = query.filter(
            (QuizQuestion.text.ilike(f"%{search}%")) |
            (QuizQuestion.subject.ilike(f"%{search}%"))
        )
    query = query.order_by(desc(QuizQuestion.generated_at)).limit(limit).offset(offset)
    return [QuizQuestionAdminOut.model_validate(q) for q in query.all()]


@router.patch("/quiz/questions/{question_id}", response_model=QuizQuestionAdminOut)
async def update_question(
    question_id: UUID,
    body: QuizQuestionUpdateIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    q = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(q, field, value)

    q.reviewed_by = admin.id
    q.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(q)
    return QuizQuestionAdminOut.model_validate(q)


@router.get("/quiz/coverage-report")
async def question_coverage_report(
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Show question counts per exam_tag and grade_or_tag.
    Highlights any tag/grade with zero live questions — a critical content gap."""
    exam_counts = (
        db.query(QuizQuestion.exam_tag, func.count(QuizQuestion.id))
        .filter(QuizQuestion.status == QuestionStatus.live, QuizQuestion.exam_tag.isnot(None))
        .group_by(QuizQuestion.exam_tag)
        .all()
    )

    grade_counts = (
        db.query(QuizQuestion.grade_or_tag, func.count(QuizQuestion.id))
        .filter(QuizQuestion.status == QuestionStatus.live, QuizQuestion.grade_or_tag.isnot(None))
        .group_by(QuizQuestion.grade_or_tag)
        .all()
    )

    grade_map = {r[0]: r[1] for r in grade_counts}
    all_grades = [row.grade_or_tag for row in db.query(GradeSubject.grade_or_tag).distinct().all()]

    zero_gaps = [g for g in all_grades if grade_map.get(g, 0) == 0]

    return {
        "exam_tag_counts": [{"tag": r[0], "count": r[1]} for r in exam_counts],
        "grade_counts": [{"grade": g, "count": grade_map.get(g, 0)} for g in all_grades],
        "zero_coverage_grades": zero_gaps,
        "total_live_questions": sum(r[1] for r in exam_counts) + sum(r[1] for r in grade_counts),
    }


@router.delete("/quiz/questions/{question_id}")
async def delete_question(
    question_id: UUID,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Permanently delete a question from the library."""
    q = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(q)
    db.commit()
    return {"deleted": str(question_id)}


@router.post("/quiz/generate")
async def trigger_question_generation(
    subject: Optional[str] = None,
    exam_tag: Optional[str] = None,
    grade_or_tag: Optional[str] = None,
    count_per_combo: int = 20,
    admin=Depends(get_current_admin),
):
    """Trigger async Cerebras question generation. Questions go live immediately on creation.
    - Specify subject+exam_tag OR subject+grade_or_tag for a specific combo.
    - Omit all to generate for all exam-tag and grade-subject combos."""
    from app.tasks.question_generation import generate_quiz_questions
    generate_quiz_questions.delay(subject=subject, exam_tag=exam_tag, grade_or_tag=grade_or_tag, count_per_combo=count_per_combo)
    return {
        "status": "queued",
        "message": "Question generation job queued. Questions will appear live within a few minutes.",
    }


# ─── Rewards ─────────────────────────────────────────────────────────────────

@router.get("/rewards", response_model=list[RewardDetailOut])
async def list_rewards(
    status: Optional[str] = Query(None),
    track: Optional[str] = Query(None),
    period_month: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    query = db.query(Reward)
    if status:
        query = query.filter(Reward.status == status)
    if track:
        query = query.filter(Reward.track == track)
    if period_month:
        query = query.filter(Reward.period_month == period_month)
    query = query.order_by(desc(Reward.created_at)).limit(limit).offset(offset)
    rewards = query.all()
    users = {u.id: u for u in db.query(User).filter(User.id.in_([r.user_id for r in rewards])).all()}
    return [_enrich_reward(r, users.get(r.user_id)) for r in rewards]


@router.patch("/rewards/{reward_id}/status")
async def update_reward_status(
    reward_id: UUID,
    new_status: str,
    notes: Optional[str] = None,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    if not reward:
        raise HTTPException(status_code=404, detail="Reward not found")

    # KYC-only transitions for superadmin
    if new_status in ("approved", "sent") and admin.admin_role != AdminRole.superadmin:
        raise HTTPException(status_code=403, detail="Superadmin required for payout actions")

    reward.status = new_status
    reward.admin_notes = notes
    if new_status == "sent":
        reward.sent_at = datetime.now(timezone.utc)

    log = AdminActionLog(
        admin_id=admin.id,
        action_type=f"reward_{new_status}",
        target_user_id=reward.user_id,
        target_resource_type="reward",
        target_resource_id=str(reward_id),
        notes=notes,
    )
    db.add(log)
    db.commit()
    return {"status": "ok", "reward_id": str(reward_id), "new_status": new_status}


# ─── Analytics ────────────────────────────────────────────────────────────────

@router.get("/analytics/revenue")
async def get_revenue_analytics(
    days: int = Query(30, le=365),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    is_pg = "postgresql" in str(db.bind.url) if db.bind else False
    # BUG FIX: func.strftime on SQLite returns a string; SQLAlchemy tries to apply
    # the Date column processor (fromisoformat) → TypeError. Cast to String to avoid it.
    if is_pg:
        day_expr = func.date_trunc("day", AdRevenueLog.date).label("day")
    else:
        from sqlalchemy import cast, String
        day_expr = cast(func.strftime("%Y-%m-%d", AdRevenueLog.date), String).label("day")
    rows = (
        db.query(
            day_expr,
            AdRevenueLog.placement_type,
            func.sum(AdRevenueLog.estimated_revenue_usd).label("revenue"),
            func.sum(AdRevenueLog.impressions).label("impressions"),
        )
        .filter(AdRevenueLog.date >= since)
        .group_by("day", AdRevenueLog.placement_type)
        .order_by("day")
        .all()
    )
    return [
        {
            "day": str(r.day)[:10] if r.day else None,
            "placement_type": r.placement_type,
            "revenue_usd": float(r.revenue or 0),
            "impressions": int(r.impressions or 0),
        }
        for r in rows
    ]


@router.get("/analytics/dau")
async def get_dau_analytics(
    days: int = Query(30, le=365),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    is_pg = "postgresql" in str(db.bind.url) if db.bind else False
    # BUG FIX: func.strftime on SQLite returns a string; SQLAlchemy tries to apply
    # the Date column processor (fromisoformat) → TypeError. Cast to String to avoid it.
    if is_pg:
        day_expr = func.date_trunc("day", StudySession.start_time).label("day")
    else:
        from sqlalchemy import cast, String
        day_expr = cast(func.strftime("%Y-%m-%d", StudySession.start_time), String).label("day")
    rows = (
        db.query(
            day_expr,
            func.count(func.distinct(StudySession.user_id)).label("dau"),
            func.count(StudySession.id).label("sessions"),
            func.sum(StudySession.verified_minutes).label("total_minutes"),
        )
        .filter(StudySession.start_time >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )
    return [
        {
            "day": str(r.day)[:10] if r.day else None,
            "dau": int(r.dau or 0),
            "sessions": int(r.sessions or 0),
            "total_minutes": int(r.total_minutes or 0),
        }
        for r in rows
    ]


# ─── Academic / Student Reports ───────────────────────────────────────────────

@router.get("/students/report")
async def student_academic_report(
    institution_type: Optional[str] = Query(None),
    class_or_year: Optional[str] = Query(None),
    exam_tag: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """
    Student academic report — used for question generation context and admin analytics.
    Returns users enriched with their academic profile.
    """
    query = db.query(User).filter(User.profile_complete == True)

    if institution_type:
        query = query.filter(User.institution_type == institution_type)
    if class_or_year:
        query = query.filter(User.class_or_year == class_or_year)
    if exam_tag:
        query = query.filter(User.exam_tags.contains([exam_tag]))

    users = query.order_by(desc(User.created_at)).limit(limit).offset(offset).all()

    return [
        {
            "id": str(u.id),
            "display_name": u.display_name,
            "full_name": u.full_name,
            "age": u.age,
            "institution_type": u.institution_type.value if u.institution_type else None,
            "institution_name": u.institution_name,
            "class_or_year": u.class_or_year,
            "exam_tags": u.exam_tags,
            "points_total": u.points_total,
            "verified_minutes_total": u.verified_minutes_total,
            "streak_count": u.streak_count,
            "country": u.country,
        }
        for u in users
    ]


@router.get("/students/class-distribution")
async def class_distribution(
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Count of students per class/year — useful for understanding the user base."""
    rows = (
        db.query(
            User.class_or_year,
            User.institution_type,
            func.count(User.id).label("count"),
        )
        .filter(User.class_or_year.isnot(None))
        .group_by(User.class_or_year, User.institution_type)
        .order_by(User.institution_type, User.class_or_year)
        .all()
    )
    return [
        {
            "class_or_year": r.class_or_year,
            "institution_type": r.institution_type.value if r.institution_type else None,
            "count": r.count,
        }
        for r in rows
    ]


@router.post("/tasks/advance-classes")
async def manual_class_advance(
    admin=Depends(get_current_superadmin),
):
    from app.tasks.class_auto_advance import advance_all_classes
    task = advance_all_classes.delay()
    return {
        "status": "queued",
        "task_id": task.id,
        "message": "Class auto-advance job has been queued. Check worker logs for progress.",
    }


# ─── Exam Tags ────────────────────────────────────────────────────────────────

@router.get("/exam-tags")
async def list_exam_tags(
    search: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Get all distinct exam tags with user and question counts, enriched with country + category."""
    from collections import Counter
    from app.core.constants import EXAM_TAGS_BY_COUNTRY

    # Build country + category lookup from constants
    tag_meta: dict[str, dict] = {}
    for cntry, tags in EXAM_TAGS_BY_COUNTRY.items():
        for t in tags:
            tag_meta[t["tag"]] = {"country": cntry, "category": t["category"]}

    # Collect tags from users (JSON column)
    user_tag_counts: Counter = Counter()
    users = db.query(User.exam_tags).filter(User.exam_tags.isnot(None)).all()
    for (tags,) in users:
        if tags and isinstance(tags, list):
            for t in tags:
                user_tag_counts[t] += 1

    # Count questions per exam tag
    question_rows = (
        db.query(QuizQuestion.exam_tag, func.count(QuizQuestion.id))
        .filter(QuizQuestion.exam_tag.isnot(None))
        .group_by(QuizQuestion.exam_tag)
        .all()
    )
    qt_map = {r[0]: r[1] for r in question_rows}

    all_tags = set(user_tag_counts.keys()) | set(qt_map.keys())
    result = []
    for tag in sorted(all_tags):
        meta = tag_meta.get(tag, {"country": None, "category": None})
        if search and search.lower() not in tag.lower():
            continue
        if country and meta["country"] != country:
            continue
        if category and meta["category"] != category:
            continue
        result.append({
            "tag": tag,
            "country": meta["country"],
            "category": meta["category"],
            "user_count": user_tag_counts.get(tag, 0),
            "question_count": qt_map.get(tag, 0),
        })
    return sorted(result, key=lambda x: x["user_count"], reverse=True)


# ─── OTP Logs ──────────────────────────────────────────────────────────────────

class OTPLogOut(BaseModel):
    id: str
    email: str
    verified: bool
    created_at: str
    verified_at: Optional[str] = None
    ip_address: Optional[str] = None


# (removed — replaced by paginated version below)


@router.get("/otp-logs/count")
async def otp_logs_count(
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Get OTP log summary counts."""
    total = db.query(func.count(OTPLog.id)).scalar() or 0
    verified = db.query(func.count(OTPLog.id)).filter(OTPLog.verified == True).scalar() or 0
    expired = db.query(func.count(OTPLog.id)).filter(OTPLog.verified == False).scalar() or 0
    return {"total": total, "verified": verified, "expired": expired}


# ─── Admin Roles ───────────────────────────────────────────────────────────────

@router.get("/admin-roles")
async def list_admin_users(
    admin=Depends(get_current_superadmin),
    db: DBSession = Depends(get_db),
):
    """List all users with admin roles."""
    users = (
        db.query(User)
        .filter(User.admin_role.isnot(None))
        .order_by(User.admin_role, User.display_name)
        .all()
    )
    return [
        {
            "id": str(u.id),
            "display_name": u.display_name,
            "email": u.email,
            "admin_role": u.admin_role.value if u.admin_role else None,
            "created_at": u.created_at.isoformat(),
            "last_active": u.last_active.isoformat() if u.last_active else None,
        }
        for u in users
    ]


@router.patch("/admin-roles/{user_id}")
async def update_admin_role(
    user_id: UUID,
    admin_role: str,
    admin=Depends(get_current_superadmin),
    db: DBSession = Depends(get_db),
):
    """Change a user's admin role."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        user.admin_role = AdminRole[admin_role]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {admin_role}")
    db.commit()
    return {"status": "ok", "user_id": str(user_id), "new_role": admin_role}


# ─── Settings Persistence ─────────────────────────────────────────────────────

from app.services.settings_service import get_all_settings as _get_all_settings, update_settings as _update_settings


@router.get("/settings")
async def get_settings(
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Get all admin-configurable settings (DB-backed)."""
    defaults = {
        "budget_cap_percent": str(settings.REWARD_BUDGET_CAP_PERCENT),
        "reward_rank_1_usd": "100",
        "reward_rank_2_usd": "75",
        "reward_rank_3_usd": "50",
        "auto_freeze_day": "28",
        "base_points_per_hour": str(settings.BASE_POINTS_PER_HOUR),
        "diminishing_after_hours": str(settings.DIMINISHING_RETURNS_AFTER_HOURS),
        "max_daily_hours_flag": str(settings.MAX_DAILY_HOURS_FLAG),
        "max_daily_ad_doubles": "2",
        "social_unlock_per_hour": str(settings.SOCIAL_UNLOCK_MINUTES_PER_HOUR),
        "social_ad_bonus_minutes": str(settings.SOCIAL_UNLOCK_AD_BONUS_MINUTES),
        "social_ad_cooldown_hours": str(settings.SOCIAL_UNLOCK_AD_COOLDOWN_HOURS),
        "quiz_set_size": str(settings.QUIZ_SET_SIZE),
        "quiz_time_limit_secs": str(settings.QUIZ_QUESTION_TIME_LIMIT_SECONDS),
        "max_quiz_attempts_per_day": str(settings.MAX_QUIZ_ATTEMPTS_PER_SUBJECT_PER_DAY),
        "quiz_base_points_per_correct": "10",
        "cerebras_model": settings.CEREBRAS_MODEL,
        "questions_per_batch": "20",
        "auto_approve_threshold": "0",
        "app_latest_version": "1.0.0",
        "app_min_version": "1.0.0",
        "app_update_url": "https://api.quovex.online/downloads/app-release.apk",
        "app_force_update": "false",
        "app_release_notes": "",
    }
    return _get_all_settings(db, defaults)


@router.put("/settings")
async def update_settings(
    body: Dict[str, str] = Body(...),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Update admin-configurable settings (DB-backed)."""
    _update_settings(db, body)
    return {"status": "ok", "updated": list(body.keys())}


# ─── Geo Analytics ────────────────────────────────────────────────────────────

@router.get("/analytics/geo")
async def geo_analytics(
    days: int = Query(30, le=365),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """DAU and revenue breakdown by country."""
    return get_geo_breakdown(db, days)


@router.get("/analytics/divergence")
async def divergence_analytics(
    days: int = Query(30, le=365),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Points-vs-verified-minutes divergence analysis for ad-grinding detection."""
    return get_divergence_analysis(db, days)


# ─── Cache & Freeze ───────────────────────────────────────────────────────────

# ─── Notifications ────────────────────────────────────────────────────────────

@router.post("/notifications/broadcast")
async def broadcast_push(
    body: NotificationComposePush,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Send a push notification to all users (or a filtered segment)."""
    result = broadcast_notification(
        db,
        title=body.title,
        body=body.body,
        notification_type="admin_broadcast",
        trigger_reason=body.trigger_reason or "admin_broadcast",
        segment_filter=body.segment_filter,
    )
    return {"status": "ok", **result}


@router.post("/tasks/freeze-leaderboard")
async def trigger_leaderboard_freeze(
    admin=Depends(get_current_superadmin),
):
    """Manually trigger leaderboard freeze and reward generation."""
    task = freeze_leaderboard.delay()
    return {
        "status": "queued",
        "task_id": task.id,
        "message": "Leaderboard freeze job queued. Rewards will be created for top performers.",
    }


@router.post("/cache/flush")
async def flush_cache(
    admin=Depends(get_current_admin),
    redis=Depends(get_redis),
):
    """Flush all Redis leaderboard caches."""
    if not redis:
        return {"status": "skipped", "flushed_keys": 0, "message": "Redis not available"}
    keys = await redis.keys("leaderboard:*")
    if keys:
        await redis.delete(*keys)
    return {"status": "ok", "flushed_keys": len(keys)}


# ═══════════════════════════════════════════════════════════════════════════════
# FRONTEND-COMPATIBLE ALIASES — map frontend API calls to existing endpoints
# ═══════════════════════════════════════════════════════════════════════════════


# ─── Anti-Cheat Aliases ─────────────────────────────────────────────────────

@router.get("/anti-cheat", response_model=list[AdminSessionFlagOut])
async def get_flagged_sessions_alias(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible alias: GET /admin/anti-cheat → GET /admin/anti-cheat/flagged"""
    sessions = (
        db.query(StudySession)
        .filter(StudySession.flagged == True)
        .order_by(desc(StudySession.start_time))
        .limit(limit).offset(offset)
        .all()
    )
    result = []
    for s in sessions:
        user = db.query(User).filter(User.id == s.user_id).first()
        out = AdminSessionFlagOut.model_validate(s)
        out.user_name = user.display_name if user else None
        result.append(out)
    return result


@router.patch("/anti-cheat/{session_id}")
async def action_flagged_session_alias(
    session_id: UUID,
    body: AdminSessionActionIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible alias: PATCH /admin/anti-cheat/{id}"""
    session = db.query(StudySession).filter(StudySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if body.action == "approve":
        session.flagged = False
        session.verified_minutes = session.raw_minutes
        user = db.query(User).filter(User.id == session.user_id).first()
        if user:
            user.verified_minutes_total += session.verified_minutes
    elif body.action == "reject":
        session.verified_minutes = 0
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    log = AdminActionLog(
        admin_id=admin.id,
        action_type=f"session_{body.action}",
        target_user_id=session.user_id,
        target_resource_type="session",
        target_resource_id=str(session_id),
        notes=body.notes,
    )
    db.add(log)
    db.commit()
    return {"status": "ok", "action": body.action}


# ─── Quiz Wrapped ───────────────────────────────────────────────────────────

@router.get("/quiz")
async def list_questions_wrapped(
    status: Optional[str] = Query("live"),
    subject: Optional[str] = Query(None),
    exam_tag: Optional[str] = Query(None),
    grade_or_tag: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: GET /admin/quiz → wrapped {questions, total, by_difficulty, by_subject, by_exam, by_grade}"""
    query = db.query(QuizQuestion)
    if status:
        try:
            query = query.filter(QuizQuestion.status == QuestionStatus[status])
        except KeyError:
            pass
    if subject:
        query = query.filter(QuizQuestion.subject == subject)
    if exam_tag:
        query = query.filter(QuizQuestion.exam_tag == exam_tag)
    if grade_or_tag:
        query = query.filter(QuizQuestion.grade_or_tag == grade_or_tag)
    if difficulty:
        query = query.filter(QuizQuestion.difficulty == difficulty)
    if search:
        query = query.filter(
            (QuizQuestion.text.ilike(f"%{search}%")) |
            (QuizQuestion.subject.ilike(f"%{search}%"))
        )

    total = query.count()
    questions = query.order_by(desc(QuizQuestion.generated_at)).limit(limit).offset(offset).all()

    # Aggregations
    by_difficulty = {}
    by_subject = {}
    by_exam = {}
    by_grade = {}
    all_q = db.query(QuizQuestion).all()
    for q in all_q:
        d = q.difficulty.value if q.difficulty else "unknown"
        by_difficulty[d] = by_difficulty.get(d, 0) + 1
        s = q.subject or "unknown"
        by_subject[s] = by_subject.get(s, 0) + 1
        e = q.exam_tag or "unknown"
        by_exam[e] = by_exam.get(e, 0) + 1
        g = q.grade_or_tag or "unknown"
        by_grade[g] = by_grade.get(g, 0) + 1

    return {
        "questions": [QuizQuestionAdminOut.model_validate(q) for q in questions],
        "total": total,
        "by_difficulty": by_difficulty,
        "by_subject": by_subject,
        "by_exam": by_exam,
        "by_grade": by_grade,
    }


# ─── Students Aliases ──────────────────────────────────────────────────────

@router.get("/students")
async def student_academic_report_alias(
    institution_type: Optional[str] = Query(None),
    class_or_year: Optional[str] = Query(None),
    exam_tag: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: GET /admin/students"""
    query = db.query(User).filter(User.profile_complete == True)
    if institution_type:
        query = query.filter(User.institution_type == institution_type)
    if class_or_year:
        query = query.filter(User.class_or_year == class_or_year)
    if exam_tag:
        query = query.filter(User.exam_tags.contains([exam_tag]))
    users = query.order_by(desc(User.created_at)).limit(limit).offset(offset).all()
    return [
        {
            "id": str(u.id),
            "display_name": u.display_name,
            "full_name": u.full_name,
            "age": u.age,
            "institution_type": u.institution_type.value if u.institution_type else None,
            "institution_name": u.institution_name,
            "class_or_year": u.class_or_year,
            "exam_tags": u.exam_tags,
            "points_total": u.points_total,
            "verified_minutes_total": u.verified_minutes_total,
            "streak_count": u.streak_count,
            "country": u.country,
            "daily_study_target_minutes": u.daily_study_target_minutes,
        }
        for u in users
    ]


@router.post("/students/advance-classes")
async def manual_class_advance_alias(
    admin=Depends(get_current_superadmin),
):
    """Frontend-compatible: POST /admin/students/advance-classes"""
    from app.tasks.class_auto_advance import advance_all_classes
    task = advance_all_classes.delay()
    return {
        "status": "queued",
        "task_id": task.id,
        "message": "Class auto-advance job has been queued.",
    }


# ─── Notifications Aliases ─────────────────────────────────────────────────

@router.post("/notifications/send")
async def broadcast_push_alias(
    body: NotificationComposePush,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: POST /admin/notifications/send"""
    seg_filter = {}
    if body.segment_country:
        seg_filter["country"] = body.segment_country
    if body.segment_exam_tag:
        seg_filter["exam_tag"] = body.segment_exam_tag
    if body.segment_streak_min:
        seg_filter["streak_min"] = body.segment_streak_min
    if body.segment_inactive_days:
        seg_filter["inactive_days"] = body.segment_inactive_days
    result = broadcast_notification(
        db,
        title=body.title,
        body=body.body,
        notification_type="admin_broadcast",
        trigger_reason="admin_broadcast",
        segment_filter=json.dumps(seg_filter) if seg_filter else None,
    )
    return {"status": "ok", **result}


@router.get("/notifications/history")
async def notification_history(
    type: Optional[str] = Query(None, alias="type"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: GET /admin/notifications/history"""
    query = db.query(NotificationLog).order_by(desc(NotificationLog.sent_at))
    if type:
        query = query.filter(NotificationLog.notification_type == type)
    if from_date:
        try:
            fd = datetime.fromisoformat(from_date)
            query = query.filter(NotificationLog.sent_at >= fd)
        except ValueError:
            pass
    if to_date:
        try:
            td = datetime.fromisoformat(to_date)
            query = query.filter(NotificationLog.sent_at <= td)
        except ValueError:
            pass
    logs = query.all()
    return [
        {
            "id": str(l.id),
            "created_at": l.sent_at.isoformat() if l.sent_at else None,
            "title": l.title,
            "notification_type": l.notification_type,
            "trigger": l.notification_type,
            "sent_count": l.recipient_count or 0,
            "skipped_count": 0,
        }
        for l in logs
    ]


# ─── Leaderboards ──────────────────────────────────────────────────────────

@router.get("/leaderboards")
async def admin_leaderboards(
    track: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: GET /admin/leaderboards"""
    query = db.query(LeaderboardSnapshot)
    if track:
        try:
            query = query.filter(LeaderboardSnapshot.track == LeaderboardTrack[track])
        except KeyError:
            pass
    if period:
        try:
            query = query.filter(LeaderboardSnapshot.period == LeaderboardPeriod[period])
        except KeyError:
            pass
    query = query.order_by(LeaderboardSnapshot.rank).limit(limit).offset(offset)
    entries = query.all()
    users_map = {str(u.id): u for u in db.query(User).filter(User.id.in_([e.user_id for e in entries])).all()}
    return {
        "entries": [
            {
                "user_id": str(e.user_id),
                "display_name": (users_map.get(str(e.user_id)).display_name if users_map.get(str(e.user_id)) else None),
                "avatar_url": (users_map.get(str(e.user_id)).avatar_url if users_map.get(str(e.user_id)) else None),
                "country": e.country or (users_map.get(str(e.user_id)).country if users_map.get(str(e.user_id)) else None),
                "streak_count": (users_map.get(str(e.user_id)).streak_count if users_map.get(str(e.user_id)) else 0),
                "rank": e.rank,
                "score": e.points or e.verified_minutes or e.verified_quiz_score or 0,
                "exam_tag": e.exam_tag,
                "is_frozen": e.is_frozen,
            }
            for e in entries
        ],
        "total": len(entries),
    }


@router.get("/leaderboards/freeze-status")
async def leaderboard_freeze_status(
    exclude_flagged: bool = Query(False),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: GET /admin/leaderboards/freeze-status"""
    tracks = ["study", "quiz", "overall"]
    result = []
    for track_name in tracks:
        try:
            track_enum = LeaderboardTrack[track_name]
        except KeyError:
            continue
        snapshots = (
            db.query(LeaderboardSnapshot)
            .filter(LeaderboardSnapshot.track == track_enum)
            .filter(LeaderboardSnapshot.period == LeaderboardPeriod.month)
            .order_by(LeaderboardSnapshot.rank)
            .limit(10)
            .all()
        )
        entries = []
        for s in snapshots:
            user = db.query(User).filter(User.id == s.user_id).first()
            if exclude_flagged and user and user.is_banned:
                continue
            entries.append({
                "rank": s.rank,
                "user_id": str(s.user_id),
                "display_name": user.display_name if user else "Unknown",
                "score": s.points or s.verified_minutes or s.verified_quiz_score or 0,
                "country": s.country,
                "is_frozen": s.is_frozen,
                "is_flagged": user.is_banned if user else False,
            })
        result.append({"track": track_name, "entries": entries})
    return {"tracks": result, "exclude_flagged": exclude_flagged}


@router.post("/leaderboards/freeze")
async def trigger_leaderboard_freeze_alias(
    admin=Depends(get_current_superadmin),
):
    """Frontend-compatible: POST /admin/leaderboards/freeze"""
    task = freeze_leaderboard.delay()
    return {
        "status": "queued",
        "task_id": task.id,
        "message": "Leaderboard freeze job queued.",
    }


# ─── Admin Roles Aliases ───────────────────────────────────────────────────

@router.get("/roles")
async def list_admin_users_alias(
    admin=Depends(get_current_superadmin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: GET /admin/roles"""
    users = (
        db.query(User)
        .filter(User.admin_role.isnot(None))
        .order_by(User.admin_role, User.display_name)
        .all()
    )
    return [
        {
            "id": str(u.id),
            "display_name": u.display_name,
            "email": u.email,
            "admin_role": u.admin_role.value if u.admin_role else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_active": u.last_active.isoformat() if u.last_active else None,
        }
        for u in users
    ]


@router.patch("/roles/{user_id}")
async def update_admin_role_alias(
    user_id: UUID,
    body: dict,
    admin=Depends(get_current_superadmin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: PATCH /admin/roles/{id} with {admin_role: ...}"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    role_str = body.get("admin_role")
    if not role_str:
        raise HTTPException(status_code=400, detail="admin_role required")
    try:
        user.admin_role = AdminRole[role_str]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {role_str}")
    db.commit()
    return {"status": "ok", "user_id": str(user_id), "new_role": role_str}


# ─── Analytics Overview ───────────────────────────────────────────────────

@router.get("/analytics/overview")
async def analytics_overview(
    days: int = Query(30, le=365),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: GET /admin/analytics/overview"""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    from sqlalchemy import cast, Date
    dau_subq = (
        db.query(
            cast(StudySession.start_time, Date).label("day"),
            func.count(func.distinct(StudySession.user_id)).label("cnt"),
        )
        .filter(StudySession.start_time >= since)
        .group_by(cast(StudySession.start_time, Date))
        .subquery()
    )
    avg_dau_row = db.query(func.avg(dau_subq.c.cnt)).scalar()
    avg_dau = int(avg_dau_row) if avg_dau_row else 0

    total_sessions = (
        db.query(func.count(StudySession.id))
        .filter(StudySession.start_time >= since)
        .scalar() or 0
    )

    total_study_time = (
        db.query(func.sum(StudySession.verified_minutes))
        .filter(StudySession.start_time >= since)
        .scalar() or 0
    )

    total_ad_revenue = (
        db.query(func.sum(AdRevenueLog.estimated_revenue_usd))
        .filter(AdRevenueLog.date >= since)
        .scalar() or 0.0
    )

    avg_revenue_per_user = 0
    total_users_count = db.query(func.count(User.id)).scalar() or 1
    if total_users_count > 0:
        avg_revenue_per_user = total_ad_revenue / total_users_count

    return {
        "avg_dau": int(avg_dau),
        "total_sessions": int(total_sessions),
        "total_study_time": int(total_study_time),
        "total_ad_revenue": round(total_ad_revenue, 2),
        "avg_revenue_per_user": round(avg_revenue_per_user, 4),
    }


# ─── OTP Logs Paginated ──────────────────────────────────────────────────

class OTPLogPaginatedOut(BaseModel):
    data: list[dict]
    total: int
    page: int
    per_page: int


@router.get("/otp-logs-paginated", response_model=OTPLogPaginatedOut)
@router.get("/otp-logs", response_model=OTPLogPaginatedOut)
async def list_otp_logs_paginated(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible paginated OTP logs."""
    query = db.query(OTPLog)
    if status == "verified":
        query = query.filter(OTPLog.verified == True)
    elif status == "expired":
        query = query.filter(OTPLog.verified == False)
    if search:
        query = query.filter(OTPLog.email.ilike(f"%{search}%"))
    total = query.count()
    logs = query.order_by(desc(OTPLog.created_at)).limit(per_page).offset((page - 1) * per_page).all()
    return {
        "data": [
            {
                "id": str(l.id),
                "email": l.email,
                "status": "verified" if l.verified else ("expired" if l.verified_at else "pending"),
                "sent_at": l.created_at.isoformat() if l.created_at else None,
                "verified_at": l.verified_at.isoformat() if l.verified_at else None,
                "ip_address": l.ip_address,
            }
            for l in logs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REWARDS — full CRUD under /admin/rewards/ prefix (frontend-compatible)
# ═══════════════════════════════════════════════════════════════════════════════

from app.api.v1.rewards import (
    RewardCreateIn, RewardEditIn, ManualKYCApprovalIn, RewardDetailOut, RewardSummaryOut,
    _enrich_reward,
)
from app.services.notification_service import send_reward_notification


@router.get("/rewards/summary", response_model=RewardSummaryOut)
async def admin_reward_summary_alias(
    period_month: Optional[str] = Query(None),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: GET /admin/rewards/summary"""
    query = db.query(Reward)
    if period_month:
        query = query.filter(Reward.period_month == period_month)
    all_rewards = query.all()
    pending = sum(1 for r in all_rewards if r.status == RewardStatus.pending)
    kyc_review = sum(1 for r in all_rewards if r.status == RewardStatus.kyc_review)
    approved = sum(1 for r in all_rewards if r.status == RewardStatus.approved)
    sent_count = sum(1 for r in all_rewards if r.status == RewardStatus.sent)
    cash_total = sum(r.reward_amount_usd or 0 for r in all_rewards if r.reward_type == RewardType.giftcard)
    budget_used = sum(
        r.reward_amount_usd or 0
        for r in all_rewards
        if r.reward_type == RewardType.giftcard and r.status == RewardStatus.sent
    )
    return RewardSummaryOut(
        total_rewards_this_month=len(all_rewards),
        total_cash_value_usd=cash_total,
        pending_count=pending,
        kyc_review_count=kyc_review,
        approved_count=approved,
        sent_count=sent_count,
        budget_used_usd=budget_used,
    )


@router.get("/rewards/{reward_id}", response_model=RewardDetailOut)
async def admin_get_reward(
    reward_id: UUID,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: GET /admin/rewards/{id}"""
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    if not reward:
        raise HTTPException(status_code=404, detail="Reward not found")
    user = db.query(User).filter(User.id == reward.user_id).first()
    return _enrich_reward(reward, user)


@router.patch("/rewards/{reward_id}", response_model=RewardDetailOut)
async def admin_update_reward(
    reward_id: UUID,
    body: RewardEditIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: PATCH /admin/rewards/{id}"""
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    if not reward:
        raise HTTPException(status_code=404, detail="Reward not found")
    if body.status in (RewardStatus.approved, RewardStatus.sent):
        if admin.admin_role != AdminRole.superadmin:
            raise HTTPException(status_code=403, detail="Superadmin required for payout actions")
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(reward, field, value)
    if body.status == RewardStatus.sent and not reward.sent_at:
        reward.sent_at = datetime.now(timezone.utc)
    log = AdminActionLog(
        admin_id=admin.id,
        action_type="reward_edit",
        target_user_id=reward.user_id,
        target_resource_type="reward",
        target_resource_id=str(reward_id),
        notes=f"Edited: {list(update_data.keys())}",
    )
    db.add(log)
    db.commit()
    db.refresh(reward)
    user = db.query(User).filter(User.id == reward.user_id).first()
    if user:
        if body.status == RewardStatus.approved:
            send_reward_notification(db, user, "kyc_approved", reward_amount=reward.reward_amount_usd)
        elif body.status == RewardStatus.sent:
            send_reward_notification(db, user, "reward_sent", reward_amount=reward.reward_amount_usd)
    return _enrich_reward(reward, user)


@router.post("/rewards", response_model=RewardDetailOut)
async def admin_create_reward_alias(
    body: RewardCreateIn,
    admin=Depends(get_current_superadmin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: POST /admin/rewards"""
    user = db.query(User).filter(User.id == body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    reward = Reward(
        user_id=body.user_id,
        track=body.track,
        period_month=body.period_month,
        tier=body.tier,
        rank_at_freeze=body.rank_at_freeze,
        reward_type=body.reward_type,
        reward_amount_usd=body.reward_amount_usd,
        reward_description=body.reward_description,
        status=RewardStatus.pending,
    )
    db.add(reward)
    log = AdminActionLog(
        admin_id=admin.id,
        action_type="reward_manual_create",
        target_user_id=body.user_id,
        target_resource_type="reward",
        notes=f"Manual reward: {body.tier} / {body.track} / {body.period_month}",
    )
    db.add(log)
    db.commit()
    db.refresh(reward)
    send_reward_notification(db, user, "reward_created", reward_amount=body.reward_amount_usd, rank=body.rank_at_freeze, track=body.track.value if body.track else None)
    return _enrich_reward(reward, user)


@router.post("/rewards/{reward_id}/kyc", response_model=RewardDetailOut)
async def admin_manual_kyc_alias(
    reward_id: UUID,
    body: ManualKYCApprovalIn,
    admin=Depends(get_current_superadmin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: POST /admin/rewards/{id}/kyc"""
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    if not reward:
        raise HTTPException(status_code=404, detail="Reward not found")
    if reward.status not in (RewardStatus.kyc_review, RewardStatus.pending):
        raise HTTPException(status_code=400, detail=f"Reward not in KYC-reviewable state (current: {reward.status})")
    now = datetime.now(timezone.utc)
    if body.approved:
        reward.kyc_verified = True
        reward.kyc_verification_id = body.kyc_reference or f"MANUAL-{now.strftime('%Y%m%d%H%M%S')}"
        reward.status = RewardStatus.approved
        notes = f"KYC approved. Ref: {reward.kyc_verification_id}. {body.notes or ''}"
    else:
        reward.kyc_verified = False
        reward.status = RewardStatus.rejected
        notes = f"KYC rejected. Reason: {body.notes or 'Not specified'}"
    reward.admin_notes = notes
    log = AdminActionLog(
        admin_id=admin.id,
        action_type="kyc_manual_" + ("approve" if body.approved else "reject"),
        target_user_id=reward.user_id,
        target_resource_type="reward",
        target_resource_id=str(reward_id),
        notes=notes,
    )
    db.add(log)
    db.commit()
    db.refresh(reward)
    user = db.query(User).filter(User.id == reward.user_id).first()
    if user and body.approved:
        send_reward_notification(db, user, "kyc_approved", reward_amount=reward.reward_amount_usd)
    return _enrich_reward(reward, user)


@router.post("/rewards/{reward_id}/mark-sent", response_model=RewardDetailOut)
async def admin_mark_sent_alias(
    reward_id: UUID,
    notes: Optional[str] = Body(None, embed=True),
    admin=Depends(get_current_superadmin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: POST /admin/rewards/{id}/mark-sent"""
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    if not reward:
        raise HTTPException(status_code=404, detail="Reward not found")
    if reward.status != RewardStatus.approved:
        raise HTTPException(status_code=400, detail="Only approved rewards can be marked as sent")
    if not reward.kyc_verified and reward.reward_type == RewardType.giftcard:
        raise HTTPException(status_code=400, detail="KYC must be verified before sending gift card")
    reward.status = RewardStatus.sent
    reward.sent_at = datetime.now(timezone.utc)
    if notes:
        reward.admin_notes = (reward.admin_notes or "") + f"\nSent: {notes}"
    log = AdminActionLog(
        admin_id=admin.id,
        action_type="reward_mark_sent",
        target_user_id=reward.user_id,
        target_resource_type="reward",
        target_resource_id=str(reward_id),
        notes=notes,
    )
    db.add(log)
    db.commit()
    db.refresh(reward)
    user = db.query(User).filter(User.id == reward.user_id).first()
    if user:
        send_reward_notification(db, user, "reward_sent", reward_amount=reward.reward_amount_usd)
    return _enrich_reward(reward, user)


@router.delete("/rewards/{reward_id}")
async def admin_delete_reward_alias(
    reward_id: UUID,
    reason: Optional[str] = Query(None),
    admin=Depends(get_current_superadmin),
    db: DBSession = Depends(get_db),
):
    """Frontend-compatible: DELETE /admin/rewards/{id}"""
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    if not reward:
        raise HTTPException(status_code=404, detail="Reward not found")
    if reward.status == RewardStatus.sent:
        raise HTTPException(status_code=400, detail="Cannot delete an already-sent reward")
    log = AdminActionLog(
        admin_id=admin.id,
        action_type="reward_delete",
        target_user_id=reward.user_id,
        target_resource_type="reward",
        target_resource_id=str(reward_id),
        notes=reason or "Deleted via admin dashboard",
    )
    db.add(log)
    db.delete(reward)
    db.commit()
    return {"deleted": True, "reward_id": str(reward_id)}


# ═══════════════════════════════════════════════════════════════════════════════
# BADGES — admin management
# ═══════════════════════════════════════════════════════════════════════════════

from app.schemas import (
    AdminBadgeOut, AdminBadgeAwardIn, AdminBadgeStatsOut,
    AdminAppLockUserOut, AdminAppLockForceUnlockOut,
    AdminTopicCreateIn, AdminTopicUpdateIn, AdminTopicOut,
    AdminReferralStatsOut, AdminReferralUserOut,
    AdminReportOut,
)


@router.get("/badges", response_model=list[AdminBadgeStatsOut])
async def admin_list_badges(
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """List all badge codes with award counts."""
    from app.models import Badge
    rows = (
        db.query(Badge.badge_code, func.count(Badge.id).label("awarded_count"))
        .group_by(Badge.badge_code)
        .order_by(desc("awarded_count"))
        .all()
    )
    return [
        AdminBadgeStatsOut(badge_code=r.badge_code, awarded_count=r.awarded_count)
        for r in rows
    ]


@router.get("/badges/detail", response_model=list[AdminBadgeOut])
async def admin_list_badge_details(
    badge_code: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """List individual badge awards with user info."""
    from app.models import Badge
    query = db.query(Badge)
    if badge_code:
        query = query.filter(Badge.badge_code == badge_code)
    query = query.order_by(desc(Badge.earned_at)).limit(limit).offset(offset)
    badges = query.all()
    users = {u.id: u for u in db.query(User).filter(User.id.in_([b.user_id for b in badges])).all()}
    return [
        AdminBadgeOut(
            id=b.id, user_id=b.user_id,
            user_name=users.get(b.user_id).display_name if users.get(b.user_id) else None,
            badge_code=b.badge_code, earned_at=b.earned_at,
        )
        for b in badges
    ]


@router.post("/badges/award", response_model=AdminBadgeOut)
async def admin_award_badge(
    body: AdminBadgeAwardIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Manually award a badge to a user."""
    from app.models import Badge
    user = db.query(User).filter(User.id == body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    badge = Badge(user_id=body.user_id, badge_code=body.badge_code, earned_at=datetime.now(timezone.utc))
    db.add(badge)
    log = AdminActionLog(
        admin_id=admin.id, action_type="badge_award",
        target_user_id=body.user_id, notes=f"Awarded badge: {body.badge_code}",
    )
    db.add(log)
    db.commit()
    db.refresh(badge)
    return AdminBadgeOut(
        id=badge.id, user_id=badge.user_id,
        user_name=user.display_name, badge_code=badge.badge_code,
        earned_at=badge.earned_at,
    )


@router.delete("/badges/{badge_id}")
async def admin_revoke_badge(
    badge_id: UUID,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Revoke (delete) a badge."""
    from app.models import Badge
    badge = db.query(Badge).filter(Badge.id == badge_id).first()
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")
    log = AdminActionLog(
        admin_id=admin.id, action_type="badge_revoke",
        target_user_id=badge.user_id, notes=f"Revoked badge: {badge.badge_code}",
    )
    db.add(log)
    db.delete(badge)
    db.commit()
    return {"deleted": True, "badge_id": str(badge_id)}


# ═══════════════════════════════════════════════════════════════════════════════
# APP LOCK — admin management
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/app-lock/users", response_model=list[AdminAppLockUserOut])
async def admin_list_app_lock_users(
    enabled_only: bool = Query(False),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """List users with app lock info."""
    query = db.query(User)
    if enabled_only:
        query = query.filter(User.app_lock_enabled == True)
    if search:
        query = query.filter(
            (User.display_name.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%"))
        )
    query = query.order_by(desc(User.app_lock_enabled), desc(User.app_lock_credits)).limit(limit).offset(offset)
    users = query.all()
    return [
        AdminAppLockUserOut(
            user_id=u.id, display_name=u.display_name, email=u.email,
            app_lock_enabled=u.app_lock_enabled, app_lock_credits=u.app_lock_credits,
            locked_packages_count=len(u.locked_app_packages or []),
        )
        for u in users
    ]


@router.post("/app-lock/{user_id}/reset-credits", response_model=AdminAppLockForceUnlockOut)
async def admin_reset_app_lock_credits(
    user_id: UUID,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Reset a user's app lock credits to max."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.app_lock_credits = settings.APP_LOCK_MAX_CREDITS
    log = AdminActionLog(
        admin_id=admin.id, action_type="app_lock_reset_credits",
        target_user_id=user_id,
    )
    db.add(log)
    db.commit()
    return AdminAppLockForceUnlockOut(
        user_id=user_id, app_lock_enabled=user.app_lock_enabled,
        message=f"Credits reset to {settings.APP_LOCK_MAX_CREDITS}",
    )


@router.post("/app-lock/{user_id}/force-unlock", response_model=AdminAppLockForceUnlockOut)
async def admin_force_unlock_app_lock(
    user_id: UUID,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Disable app lock for a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.app_lock_enabled = False
    log = AdminActionLog(
        admin_id=admin.id, action_type="app_lock_force_unlock",
        target_user_id=user_id,
    )
    db.add(log)
    db.commit()
    return AdminAppLockForceUnlockOut(
        user_id=user_id, app_lock_enabled=False,
        message="App lock has been disabled for this user.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TOPICS — admin CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/topics", response_model=list[AdminTopicOut])
async def admin_list_topics(
    subject: Optional[str] = Query(None),
    exam_tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """List all topics with student counts."""
    from app.models import Topic as TopicModel, UserTopicProgress
    query = db.query(TopicModel)
    if subject:
        query = query.filter(TopicModel.subject == subject)
    if exam_tag:
        query = query.filter(TopicModel.exam_tag == exam_tag)
    if search:
        query = query.filter(TopicModel.name.ilike(f"%{search}%"))
    topics = query.order_by(TopicModel.display_order, TopicModel.name).all()

    # Student counts per topic
    topic_ids = [t.id for t in topics]
    count_rows = (
        db.query(UserTopicProgress.topic_id, func.count(func.distinct(UserTopicProgress.user_id)))
        .filter(UserTopicProgress.topic_id.in_(topic_ids))
        .group_by(UserTopicProgress.topic_id)
        .all()
    )
    count_map = {r[0]: r[1] for r in count_rows}

    return [
        AdminTopicOut(
            id=t.id, name=t.name, subject=t.subject,
            exam_tag=t.exam_tag, display_order=t.display_order,
            student_count=count_map.get(t.id, 0),
        )
        for t in topics
    ]


@router.post("/topics", response_model=AdminTopicOut)
async def admin_create_topic(
    body: AdminTopicCreateIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Create a new topic."""
    from app.models import Topic as TopicModel
    topic = TopicModel(name=body.name, subject=body.subject, exam_tag=body.exam_tag, display_order=body.display_order)
    db.add(topic)
    log = AdminActionLog(
        admin_id=admin.id, action_type="topic_create",
        notes=f"Created topic: {body.name} ({body.subject})",
    )
    db.add(log)
    db.commit()
    db.refresh(topic)
    return AdminTopicOut(id=topic.id, name=topic.name, subject=topic.subject, exam_tag=topic.exam_tag, display_order=topic.display_order, student_count=0)


@router.put("/topics/{topic_id}", response_model=AdminTopicOut)
async def admin_update_topic(
    topic_id: UUID,
    body: AdminTopicUpdateIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Update a topic."""
    from app.models import Topic as TopicModel
    topic = db.query(TopicModel).filter(TopicModel.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(topic, field, value)
    log = AdminActionLog(
        admin_id=admin.id, action_type="topic_update",
        target_resource_type="topic", target_resource_id=str(topic_id),
        notes=f"Updated: {list(update_data.keys())}",
    )
    db.add(log)
    db.commit()
    db.refresh(topic)

    from app.models import UserTopicProgress
    student_count = db.query(func.count(func.distinct(UserTopicProgress.user_id))).filter(UserTopicProgress.topic_id == topic_id).scalar() or 0
    return AdminTopicOut(id=topic.id, name=topic.name, subject=topic.subject, exam_tag=topic.exam_tag, display_order=topic.display_order, student_count=student_count)


@router.delete("/topics/{topic_id}")
async def admin_delete_topic(
    topic_id: UUID,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Delete a topic."""
    from app.models import Topic as TopicModel
    topic = db.query(TopicModel).filter(TopicModel.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    log = AdminActionLog(
        admin_id=admin.id, action_type="topic_delete",
        target_resource_type="topic", target_resource_id=str(topic_id),
        notes=f"Deleted topic: {topic.name}",
    )
    db.add(log)
    db.delete(topic)
    db.commit()
    return {"deleted": True, "topic_id": str(topic_id)}


# ═══════════════════════════════════════════════════════════════════════════════
# REFERRAL — admin overview
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/referral/stats", response_model=AdminReferralStatsOut)
async def admin_referral_stats(
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Overall referral stats."""
    total_referred = db.query(func.count(User.id)).filter(User.referred_by_id.isnot(None)).scalar() or 0
    total_bonus = db.query(func.sum(User.referral_bonus_earned)).scalar() or 0

    top_rows = (
        db.query(
            User.display_name, User.email,
            func.count(User.id).label("cnt"),
        )
        .join(User, User.referred_by_id == User.id, isouter=True)
        .filter(User.referred_by_id.isnot(None))
        .group_by(User.id)
        .order_by(desc("cnt"))
        .limit(10)
        .all()
    )

    return AdminReferralStatsOut(
        total_referred_users=int(total_referred),
        total_bonus_paid=int(total_bonus),
        top_referrers=[
            {"display_name": r.display_name, "email": r.email, "referred_count": r.cnt}
            for r in top_rows
        ],
    )


@router.get("/settings/referrals", response_model=AdminReferralSettingsOut)
async def admin_get_referral_settings(
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Retrieve current referral reward settings from admin panel."""
    setting = db.query(SystemSetting).filter(SystemSetting.key == "referral_rewards").first()
    vals = setting.value if (setting and isinstance(setting.value, dict)) else {}
    return AdminReferralSettingsOut(
        reward_minutes_per_referral=int(vals.get("reward_minutes_per_referral", 30)),
        reward_points_per_referral=int(vals.get("reward_points_per_referral", 50)),
        friend_welcome_bonus_minutes=int(vals.get("friend_welcome_bonus_minutes", 30)),
        min_session_minutes_to_unlock=int(vals.get("min_session_minutes_to_unlock", 25)),
        is_referral_active=bool(vals.get("is_referral_active", True))
    )


@router.put("/settings/referrals", response_model=AdminReferralSettingsOut)
async def admin_update_referral_settings(
    body: AdminReferralSettingsIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Update referral reward amounts (minutes, XP) from admin panel."""
    setting = db.query(SystemSetting).filter(SystemSetting.key == "referral_rewards").first()
    if not setting:
        setting = SystemSetting(
            key="referral_rewards",
            value={
                "reward_minutes_per_referral": 30,
                "reward_points_per_referral": 50,
                "friend_welcome_bonus_minutes": 30,
                "min_session_minutes_to_unlock": 25,
                "is_referral_active": True
            },
            description="Dynamic referral reward parameters"
        )
        db.add(setting)

    cur_vals = dict(setting.value)
    if body.reward_minutes_per_referral is not None:
        cur_vals["reward_minutes_per_referral"] = max(0, body.reward_minutes_per_referral)
    if body.reward_points_per_referral is not None:
        cur_vals["reward_points_per_referral"] = max(0, body.reward_points_per_referral)
    if body.friend_welcome_bonus_minutes is not None:
        cur_vals["friend_welcome_bonus_minutes"] = max(0, body.friend_welcome_bonus_minutes)
    if body.min_session_minutes_to_unlock is not None:
        cur_vals["min_session_minutes_to_unlock"] = max(1, body.min_session_minutes_to_unlock)
    if body.is_referral_active is not None:
        cur_vals["is_referral_active"] = body.is_referral_active

    setting.value = cur_vals
    db.commit()
    db.refresh(setting)

    return AdminReferralSettingsOut(
        reward_minutes_per_referral=int(cur_vals.get("reward_minutes_per_referral", 30)),
        reward_points_per_referral=int(cur_vals.get("reward_points_per_referral", 50)),
        friend_welcome_bonus_minutes=int(cur_vals.get("friend_welcome_bonus_minutes", 30)),
        min_session_minutes_to_unlock=int(cur_vals.get("min_session_minutes_to_unlock", 25)),
        is_referral_active=bool(cur_vals.get("is_referral_active", True))
    )


@router.get("/referral/users", response_model=list[AdminReferralUserOut])
async def admin_referral_users(
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """List users with referral info."""
    query = db.query(User)
    if search:
        query = query.filter(
            (User.display_name.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%")) |
            (User.referral_code.ilike(f"%{search}%"))
        )
    users = query.order_by(desc(User.referral_bonus_earned)).limit(limit).offset(offset).all()
    user_ids = [u.id for u in users]

    # Count referred users per referrer
    ref_counts = dict(
        db.query(User.referred_by_id, func.count(User.id))
        .filter(User.referred_by_id.in_(user_ids))
        .group_by(User.referred_by_id)
        .all()
    )

    # Get referred_by names
    referred_by_ids = [u.referred_by_id for u in users if u.referred_by_id]
    referred_by_users = {}
    if referred_by_ids:
        for u_ref in db.query(User).filter(User.id.in_(referred_by_ids)).all():
            referred_by_users[u_ref.id] = u_ref.display_name

    return [
        AdminReferralUserOut(
            user_id=u.id, display_name=u.display_name, email=u.email,
            referral_code=u.referral_code,
            referred_by_name=referred_by_users.get(u.referred_by_id) if u.referred_by_id else None,
            referred_users_count=ref_counts.get(u.id, 0),
            referral_bonus_earned=u.referral_bonus_earned,
        )
        for u in users
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTS — admin management
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/reports", response_model=list[AdminReportOut])
async def admin_list_reports(
    report_type: Optional[str] = Query(None, regex="^(daily|weekly)?$"),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """List AI-generated study reports with user info."""
    from app.models import UserReport
    query = db.query(UserReport)
    if report_type:
        query = query.filter(UserReport.report_type == report_type)
    query = query.order_by(desc(UserReport.generated_at)).limit(limit).offset(offset)
    reports = query.all()
    user_ids = list(set(r.user_id for r in reports))
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
    result = []
    for r in reports:
        user = users.get(r.user_id)
        if search and user:
            if search.lower() not in (user.email or "").lower() and search.lower() not in (user.display_name or "").lower():
                continue
        result.append(AdminReportOut(
            id=r.id, user_id=r.user_id,
            user_email=user.email if user else None,
            user_name=user.display_name if user else None,
            report_type=r.report_type,
            period_start=r.period_start, period_end=r.period_end,
            summary=r.summary[:200] + "..." if len(r.summary) > 200 else r.summary,
            generated_at=r.generated_at, read_at=r.read_at,
        ))
    return result


@router.post("/reports/{report_id}/regenerate")
async def admin_regenerate_report(
    report_id: UUID,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db),
):
    """Force-regenerate a report via Cerebras."""
    from app.models import UserReport
    report = db.query(UserReport).filter(UserReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    from app.services.report_service import generate_report
    user = db.query(User).filter(User.id == report.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    new_report = generate_report(user, report.report_type, db)
    log = AdminActionLog(
        admin_id=admin.id, action_type="report_regenerate",
        target_user_id=report.user_id,
        target_resource_type="report", target_resource_id=str(report_id),
        notes=f"Regenerated {report.report_type} report",
    )
    db.add(log)
    db.commit()
    return {
        "status": "ok",
        "new_report_id": str(new_report.id),
        "message": f"Report regenerated successfully",
    }


# ─── Support Ticket Management (Admin Panel) ─────────────────────────────────

@router.get("/support/tickets", response_model=SupportTicketListOut)
async def admin_list_support_tickets(
    status: Optional[str] = Query(None, description="Filter by status: open, in_progress, resolved, closed"),
    category: Optional[str] = Query(None, description="Filter by issue category"),
    priority: Optional[str] = Query(None, description="Filter by priority: low, medium, high, urgent"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db)
):
    """Admin endpoint to query and manage all user submitted issues."""
    from app.services import support_service
    return support_service.list_admin_tickets(
        db=db,
        status=status,
        category=category,
        priority=priority,
        limit=limit,
        offset=offset
    )


@router.get("/support/tickets/{ticket_id}", response_model=SupportTicketOut)
async def admin_get_support_ticket(
    ticket_id: UUID,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db)
):
    """Admin view full details of a specific support ticket."""
    from app.services import support_service
    ticket = support_service.get_ticket_by_id(ticket_id=ticket_id, db=db)
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    return ticket


@router.patch("/support/tickets/{ticket_id}", response_model=SupportTicketOut)
async def admin_update_support_ticket(
    ticket_id: UUID,
    body: SupportTicketUpdateIn,
    admin=Depends(get_current_admin),
    db: DBSession = Depends(get_db)
):
    """Admin update ticket resolution status, priority, and internal notes."""
    from app.services import support_service
    ticket = support_service.update_ticket_status(
        ticket_id=ticket_id,
        admin_user=admin,
        data=body,
        db=db
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    return ticket


