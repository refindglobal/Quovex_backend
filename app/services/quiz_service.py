"""Quiz service - question selection, scoring, proficiency tracking."""
import random
import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.config import settings
from app.models import (
    User, UserSubjectProficiency, QuizQuestion, QuizSession, QuizAnswer,
    QuestionStatus, Difficulty,
)

logger = logging.getLogger(__name__)

SPEED_BONUS_THRESHOLD_MS = settings.QUIZ_SPEED_BONUS_THRESHOLD_MS
BASE_POINTS_PER_CORRECT = settings.QUIZ_BASE_POINTS_PER_CORRECT
SPEED_BONUS = settings.QUIZ_SPEED_BONUS_POINTS
STREAK_BONUS = settings.QUIZ_STREAK_BONUS_POINTS


def select_questions(
    db: Session,
    user: User,
    subject: Optional[str],
    exam_tag: Optional[str],
    difficulty: Optional[str],
    count: Optional[int] = None,
    grade_or_tag: Optional[str] = None,
) -> List[QuizQuestion]:
    """Adaptive question selection (PRD §5.4)."""
    count = count or settings.QUIZ_SET_SIZE

    seen_ids = (
        db.query(QuizAnswer.question_id)
        .join(QuizSession, QuizAnswer.quiz_session_id == QuizSession.id)
        .filter(QuizSession.user_id == user.id)
        .subquery()
    )

    query = db.query(QuizQuestion).filter(
        QuizQuestion.status == QuestionStatus.live,
        ~QuizQuestion.id.in_(db.query(seen_ids.c.question_id)),
    )

    if subject:
        query = query.filter(QuizQuestion.subject == subject)
    if exam_tag:
        query = query.filter(QuizQuestion.exam_tag == exam_tag)
    if grade_or_tag:
        query = query.filter(
            (QuizQuestion.grade_or_tag == grade_or_tag) | (QuizQuestion.exam_tag == grade_or_tag)
        )

    if difficulty == Difficulty.adaptive and subject:
        prof = (
            db.query(UserSubjectProficiency)
            .filter(
                UserSubjectProficiency.user_id == user.id,
                UserSubjectProficiency.subject == subject,
            )
            .first()
        )
        accuracy = prof.rolling_accuracy_score if prof else 0.5
        if accuracy < 0.4:
            difficulties = [Difficulty.easy, Difficulty.medium]
        elif accuracy < 0.7:
            difficulties = [Difficulty.easy, Difficulty.medium, Difficulty.hard]
        else:
            difficulties = [Difficulty.medium, Difficulty.hard]
        query = query.filter(QuizQuestion.difficulty.in_(difficulties))
    elif difficulty != Difficulty.adaptive:
        query = query.filter(QuizQuestion.difficulty == difficulty)

    unseen = query.order_by(QuizQuestion.generated_at).limit(count * 5).all()
    random.shuffle(unseen)

    if len(unseen) >= count:
        return unseen[:count]

    # Fallback 1: allow previously-seen questions but keep grade/subject filter
    fallback = (
        db.query(QuizQuestion)
        .filter(QuizQuestion.status == QuestionStatus.live)
    )
    if subject:
        fallback = fallback.filter(QuizQuestion.subject == subject)
    if exam_tag:
        fallback = fallback.filter(QuizQuestion.exam_tag == exam_tag)
    if grade_or_tag:
        fallback = fallback.filter(
            (QuizQuestion.grade_or_tag == grade_or_tag) | (QuizQuestion.exam_tag == grade_or_tag)
        )

    fallback_questions = fallback.limit(count * 5).all()
    random.shuffle(fallback_questions)
    combined = unseen + [q for q in fallback_questions if q not in unseen]
    if combined:
        return combined[:count]

    # Fallback 2: subject-only match (ignore grade) — ensures something is returned
    # This is safe because the question will still be from the correct subject
    last_resort = (
        db.query(QuizQuestion)
        .filter(
            QuizQuestion.status == QuestionStatus.live,
            QuizQuestion.subject == subject,
        )
        .limit(count * 3)
        .all()
    ) if subject else []
    random.shuffle(last_resort)
    return last_resort[:count]


def check_answer(question: QuizQuestion, selected: Optional[str]) -> bool:
    if selected is None:
        return False
    return selected.strip().lower() == question.correct_answer.strip().lower()


def count_consecutive_correct(db: Session, quiz_session_id: UUID) -> int:
    answers = (
        db.query(QuizAnswer)
        .filter(QuizAnswer.quiz_session_id == quiz_session_id)
        .order_by(QuizAnswer.answered_at.desc())
        .all()
    )
    streak = 0
    for a in answers:
        if a.is_correct:
            streak += 1
        else:
            break
    return streak


def calculate_answer_points(is_correct: bool, response_time_ms: Optional[int], consecutive: int) -> int:
    if not is_correct:
        return 0
    points = BASE_POINTS_PER_CORRECT
    if response_time_ms and response_time_ms < SPEED_BONUS_THRESHOLD_MS:
        points += SPEED_BONUS
    points += consecutive * STREAK_BONUS
    return points


def update_proficiency(db: Session, user: User, quiz_session: QuizSession):
    accuracy = quiz_session.total_correct / quiz_session.total_questions if quiz_session.total_questions > 0 else 0
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")
    prof = (
        db.query(UserSubjectProficiency)
        .filter(
            UserSubjectProficiency.user_id == user.id,
            UserSubjectProficiency.subject == quiz_session.subject,
        )
        .first()
    )
    if not prof:
        prof = UserSubjectProficiency(
            user_id=user.id,
            subject=quiz_session.subject,
            exam_tag=quiz_session.exam_tag,
            rolling_accuracy_score=accuracy,
            total_questions_answered=quiz_session.total_questions,
            total_correct=quiz_session.total_correct,
            monthly_accuracy_history=[{"month": month_key, "accuracy": round(accuracy, 4)}],
        )
        db.add(prof)
    else:
        alpha = 0.3
        prof.rolling_accuracy_score = alpha * accuracy + (1 - alpha) * prof.rolling_accuracy_score
        prof.total_questions_answered += quiz_session.total_questions
        prof.total_correct += quiz_session.total_correct

        history = list(prof.monthly_accuracy_history or [])
        if history and history[-1]["month"] == month_key:
            # Update current month entry (rolling average)
            prev = history[-1]["accuracy"]
            history[-1]["accuracy"] = round((prev + accuracy) / 2, 4)
        else:
            history.append({"month": month_key, "accuracy": round(accuracy, 4)})
        prof.monthly_accuracy_history = history
    db.flush()
