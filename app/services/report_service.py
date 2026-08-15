"""AI-powered study report generation using Cerebras API."""
import json
import logging
import time
from datetime import datetime, timezone, timedelta, date
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func

from app.config import settings
from app.models import (
    User, UserReport, AppUsageLog, Session as StudySession,
    QuizSession, UserTopicProgress, Topic, Badge,
)

logger = logging.getLogger(__name__)

REPORT_PROMPT = """You are a friendly and encouraging AI study coach. Generate a {report_type} report for a student based on the following data.

Student Data (past {days} days):
- Total study minutes: {study_minutes}
- Study sessions: {session_count}
- Quiz sessions completed: {quiz_count}
- Quiz accuracy: {accuracy}%
- Subjects studied: {subjects}
- Topics with progress: {topic_progress}
- Current streak: {streak} days
- Badges earned in period: {badges}
- App opens (how many times you opened the app): {app_opens}

Return ONLY valid JSON with this structure:
{{
  "summary": "A 2-3 paragraph encouraging summary of the student's performance, highlighting effort and results",
  "highlights": {{
    "total_hours": number,
    "sessions_completed": number,
    "quizzes_completed": number,
    "avg_accuracy_pct": number,
    "subjects_studied": number,
    "streak_days": number,
    "badges_earned": number,
    "app_opens": number
  }},
  "recommendations": [
    "3-5 specific, actionable recommendations for improvement"
  ]
}}

Make the summary warm and motivating. Keep recommendations specific and realistic based on the data.
"""


def _pick_api_key() -> str:
    keys_str = settings.CEREBRAS_API_KEYS or settings.CEREBRAS_API_KEY
    if not keys_str:
        return ""
    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    import random
    return random.choice(keys) if keys else ""


def _pick_groq_key() -> str:
    keys_str = settings.GROQ_API_KEYS or settings.GROQ_API_KEY
    if not keys_str:
        return ""
    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    import random
    return random.choice(keys) if keys else ""


def _call_cerebras(prompt: str) -> dict:
    last_exc = None
    # 1. Try Cerebras
    for attempt in range(2):
        api_key = _pick_api_key()
        if not api_key:
            break
        try:
            response = httpx.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.CEREBRAS_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are an expert AI study coach. Return only valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2048,
                },
                timeout=30,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > 0:
                return json.loads(content[start:end])
        except Exception as e:
            last_exc = e
            time.sleep(0.5)

    # 2. Try Groq fallback
    groq_key = _pick_groq_key()
    if groq_key:
        try:
            logger.info("Falling back to Groq for report generation")
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are an expert AI study coach. Return only valid JSON object."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2048,
                },
                timeout=30,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > 0:
                return json.loads(content[start:end])
        except Exception as e:
            last_exc = e

    if last_exc:
        raise last_exc
    raise ValueError("No AI API keys configured or available")


def generate_report(user: User, report_type: str, db: DBSession) -> UserReport:
    now = datetime.now(timezone.utc)
    if report_type == "daily":
        period_start = now - timedelta(days=1)
    else:
        period_start = now - timedelta(days=7)

    # Collect study data
    sessions = (
        db.query(StudySession)
        .filter(
            StudySession.user_id == user.id,
            StudySession.start_time >= period_start,
            StudySession.is_active == False,
        )
        .all()
    )
    study_minutes = sum(s.verified_minutes for s in sessions)
    session_count = len(sessions)

    quiz_sessions = (
        db.query(QuizSession)
        .filter(
            QuizSession.user_id == user.id,
            QuizSession.start_time >= period_start,
            QuizSession.is_complete == True,
        )
        .all()
    )
    quiz_count = len(quiz_sessions)
    total_correct = sum(q.total_correct for q in quiz_sessions)
    total_questions = sum(q.total_questions for q in quiz_sessions)
    accuracy = round(total_correct / total_questions * 100, 1) if total_questions > 0 else 0

    subjects_set = set()
    for s in sessions:
        if s.subject_tag:
            subjects_set.add(s.subject_tag)
    for q in quiz_sessions:
        if q.subject:
            subjects_set.add(q.subject)

    topic_progress_rows = (
        db.query(UserTopicProgress, Topic)
        .join(Topic, UserTopicProgress.topic_id == Topic.id)
        .filter(
            UserTopicProgress.user_id == user.id,
            UserTopicProgress.questions_answered > 0,
        )
        .all()
    )
    topic_progress_str = "; ".join(
        f"{t.name} ({utp.questions_answered}q, {round(utp.accuracy * 100)}%)"
        for utp, t in topic_progress_rows[:5]
    ) if topic_progress_rows else "None"

    badges_earned = (
        db.query(Badge)
        .filter(
            Badge.user_id == user.id,
            Badge.earned_at >= period_start,
        )
        .count()
    )

    app_usage = (
        db.query(func.sum(AppUsageLog.open_count))
        .filter(
            AppUsageLog.user_id == user.id,
            AppUsageLog.date >= period_start,
        )
        .scalar()
    ) or 0

    prompt = REPORT_PROMPT.format(
        report_type=report_type,
        days=1 if report_type == "daily" else 7,
        study_minutes=study_minutes,
        session_count=session_count,
        quiz_count=quiz_count,
        accuracy=accuracy,
        subjects=", ".join(sorted(subjects_set)) if subjects_set else "None",
        topic_progress=topic_progress_str,
        streak=user.streak_count,
        badges=badges_earned,
        app_opens=app_usage,
    )

    try:
        result = _call_cerebras(prompt)
    except Exception as e:
        logger.error(f"Failed to generate report via Cerebras: {e}")
        result = {
            "summary": f"Great effort this {'day' if report_type == 'daily' else 'week'}! You studied for {study_minutes} minutes across {session_count} sessions. Keep it up!",
            "highlights": {
                "total_hours": round(study_minutes / 60, 1),
                "sessions_completed": session_count,
                "quizzes_completed": quiz_count,
                "avg_accuracy_pct": accuracy,
                "subjects_studied": len(subjects_set),
                "streak_days": user.streak_count,
                "badges_earned": badges_earned,
                "app_opens": app_usage,
            },
            "recommendations": [
                "Try to study at the same time each day to build a habit.",
                "Focus on weak topics identified in your quizzes.",
            ],
        }

    report = UserReport(
        user_id=user.id,
        report_type=report_type,
        period_start=period_start,
        period_end=now,
        summary=result.get("summary", ""),
        highlights=result.get("highlights"),
        recommendations=result.get("recommendations"),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
