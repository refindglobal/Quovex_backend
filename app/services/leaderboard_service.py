"""
Leaderboard service:
- Rank computation for all tracks/scopes/periods
- Redis caching with TTL
- Snapshot creation
"""
import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_, String

from app.models import (
    User, Session as StudySession, QuizSession, LeaderboardSnapshot,
    LeaderboardTrack, LeaderboardScope, LeaderboardPeriod
)


CACHE_TTL = 30  # 30 seconds for live real-time freshness


def _cache_key(track: str, scope: str, period: str, exam_tag: Optional[str] = None,
               country: Optional[str] = None, state: Optional[str] = None) -> str:
    parts = ["leaderboard", track, scope, period]
    if exam_tag:
        parts.append(f"tag:{exam_tag}")
    if country:
        parts.append(f"country:{country}")
    if state:
        parts.append(f"state:{state}")
    return ":".join(parts)


def compute_leaderboard(
    db: Session,
    track: LeaderboardTrack,
    scope: LeaderboardScope,
    period: LeaderboardPeriod,
    exam_tag: Optional[str] = None,
    country: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Compute leaderboard rankings from DB."""
    now = datetime.now(timezone.utc)

    # Determine time window
    if period == LeaderboardPeriod.week:
        since = now - timedelta(days=7)
    elif period == LeaderboardPeriod.month:
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        since = datetime(2020, 1, 1, tzinfo=timezone.utc)

    # Build the ranking query based on track
    if track == LeaderboardTrack.study:
        if period == LeaderboardPeriod.all_time:
            query = db.query(
                User.id.label("user_id"),
                User.display_name,
                User.avatar_url,
                User.country,
                User.state,
                User.streak_count,
                User.verified_minutes_total.label("score"),
            )
        else:
            rank_col = func.sum(StudySession.verified_minutes).label("score")
            query = (
                db.query(
                    User.id.label("user_id"),
                    User.display_name,
                    User.avatar_url,
                    User.country,
                    User.state,
                    User.streak_count,
                    rank_col,
                )
                .join(StudySession, StudySession.user_id == User.id)
                .filter(
                    StudySession.start_time >= since,
                    StudySession.is_active == False,
                    StudySession.flagged == False,
                )
            )
    elif track == LeaderboardTrack.quiz:
        if period == LeaderboardPeriod.all_time:
            query = db.query(
                User.id.label("user_id"),
                User.display_name,
                User.avatar_url,
                User.country,
                User.state,
                User.streak_count,
                func.greatest(
                    func.coalesce(User.quiz_points_total, 0),
                    func.coalesce(User.verified_quiz_score, 0),
                    func.coalesce(User.points_total, 0)
                ).label("score"),
            )
        else:
            query = (
                db.query(
                    User.id.label("user_id"),
                    User.display_name,
                    User.avatar_url,
                    User.country,
                    User.state,
                    User.streak_count,
                    func.greatest(
                        func.coalesce(func.sum(QuizSession.verified_quiz_score_earned), 0),
                        func.coalesce(User.quiz_points_total, 0),
                        func.coalesce(User.verified_quiz_score, 0)
                    ).label("score"),
                )
                .outerjoin(
                    QuizSession,
                    (QuizSession.user_id == User.id)
                    & (QuizSession.start_time >= since)
                    & (QuizSession.is_complete == True)
                )
            )
    else:
        if period == LeaderboardPeriod.all_time:
            query = db.query(
                User.id.label("user_id"),
                User.display_name,
                User.avatar_url,
                User.country,
                User.state,
                User.streak_count,
                func.greatest(
                    func.coalesce(User.points_total, 0),
                    func.coalesce(User.verified_minutes_total, 0) + func.coalesce(User.quiz_points_total, 0) * 0.5
                ).label("score"),
            )
        else:
            study_score = (
                db.query(
                    StudySession.user_id,
                    func.coalesce(func.sum(StudySession.verified_minutes), 0).label("study_score"),
                )
                .filter(
                    StudySession.start_time >= since,
                    StudySession.is_active == False,
                    StudySession.flagged == False,
                )
                .group_by(StudySession.user_id)
                .subquery()
            )
            quiz_score = (
                db.query(
                    QuizSession.user_id,
                    func.coalesce(func.sum(QuizSession.verified_quiz_score_earned), 0).label("quiz_score"),
                )
                .filter(
                    QuizSession.start_time >= since,
                    QuizSession.is_complete == True,
                )
                .group_by(QuizSession.user_id)
                .subquery()
            )
            query = (
                db.query(
                    User.id.label("user_id"),
                    User.display_name,
                    User.avatar_url,
                    User.country,
                    User.state,
                    User.streak_count,
                    func.greatest(
                        func.coalesce(study_score.c.study_score, 0)
                        + func.coalesce(quiz_score.c.quiz_score, 0) * 0.5,
                        func.coalesce(User.points_total, 0)
                    ).label("score"),
                )
                .outerjoin(study_score, study_score.c.user_id == User.id)
                .outerjoin(quiz_score, quiz_score.c.user_id == User.id)
            )

    # Apply scope filters
    if scope == LeaderboardScope.country and country:
        query = query.filter(User.country == country)
    elif scope == LeaderboardScope.state and state:
        query = query.filter(User.state == state)

    # Apply exam_tag filter
    if exam_tag:
        query = query.filter(
            or_(
                User.exam_target == exam_tag,
                func.cast(User.exam_tags, String).contains(exam_tag)
            )
        )

    # Group by user for aggregate-based tracks (exclude JSON columns like exam_tags)
    if track != LeaderboardTrack.overall and period != LeaderboardPeriod.all_time:
        query = query.group_by(
            User.id, User.display_name, User.avatar_url,
            User.country, User.state, User.streak_count
        )

    query = query.filter(User.is_banned == False)
    query = query.order_by(desc("score"))
    query = query.limit(limit).offset(offset)

    results = query.all()

    leaderboard = []
    for i, row in enumerate(results):
        score_val = int(row.score or 0)
        mins = score_val if track == LeaderboardTrack.study else 0
        quiz_sc = score_val if track == LeaderboardTrack.quiz else 0
        leaderboard.append({
            "rank": offset + i + 1,
            "user_id": str(row.user_id),
            "display_name": row.display_name or "Anonymous",
            "avatar_url": row.avatar_url,
            "country": row.country,
            "state": row.state,
            "streak_count": row.streak_count or 0,
            "verified_minutes": mins,
            "verified_minutes_total": mins,
            "verified_quiz_score": quiz_sc,
            "points": score_val,
            "score": score_val,
        })

    return leaderboard


async def get_leaderboard_cached(
    db: Session,
    redis,
    track: str,
    scope: str,
    period: str,
    exam_tag: Optional[str] = None,
    country: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Get leaderboard with Redis caching (gracefully falls back to DB)."""
    cache_key = _cache_key(track, scope, period, exam_tag, country, state)

    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                return data[offset:offset + limit]
        except Exception:
            pass

    # Compute from DB
    leaderboard = compute_leaderboard(
        db,
        LeaderboardTrack(track),
        LeaderboardScope(scope) if scope != "global" else LeaderboardScope.global_,
        LeaderboardPeriod(period),
        exam_tag, country, state,
        limit=200,
        offset=0,
    )

    if redis:
        try:
            await redis.setex(cache_key, CACHE_TTL, json.dumps(leaderboard))
        except Exception:
            pass

    return leaderboard[offset:offset + limit]


def get_user_rank(
    db: Session,
    user_id: UUID,
    track: str,
    scope: str,
    period: str,
) -> Optional[Dict[str, Any]]:
    """Get a specific user's current rank position."""
    full_lb = compute_leaderboard(
        db,
        LeaderboardTrack(track),
        LeaderboardScope(scope) if scope != "global" else LeaderboardScope.global_,
        LeaderboardPeriod(period),
        limit=10000,
    )
    for entry in full_lb:
        if entry["user_id"] == str(user_id):
            return entry
    return None
