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


import re

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

    clean_exam = None
    if exam_tag:
        clean_exam = re.sub(r'\b(19|20)\d{2}\b', '', exam_tag).strip() or exam_tag

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
        query = query.filter(QuizQuestion.subject.ilike(f"%{subject}%"))
    if clean_exam:
        query = query.filter(
            (QuizQuestion.exam_tag.ilike(f"%{clean_exam}%")) |
            (QuizQuestion.grade_or_tag.ilike(f"%{clean_exam}%"))
        )

    unseen = query.order_by(QuizQuestion.generated_at.desc()).limit(count * 5).all()
    random.shuffle(unseen)

    if len(unseen) >= count:
        return unseen[:count]

    # Fallback 1: match subject without exam constraint
    fallback_subject = (
        db.query(QuizQuestion)
        .filter(
            QuizQuestion.status == QuestionStatus.live,
            QuizQuestion.subject.ilike(f"%{subject}%") if subject else True
        )
        .limit(count * 5)
        .all()
    )
    random.shuffle(fallback_subject)
    combined = unseen + [q for q in fallback_subject if q not in unseen]
    if len(combined) >= count:
        return combined[:count]

    # Fallback 2: Any live questions in DB
    all_live = (
        db.query(QuizQuestion)
        .filter(QuizQuestion.status == QuestionStatus.live)
        .limit(count * 5)
        .all()
    )
    random.shuffle(all_live)
    combined = combined + [q for q in all_live if q not in combined]
    if combined:
        return combined[:count]

    # Fallback 3: If database has 0 questions, create real initial curriculum questions
    default_subj = subject or "Physics"
    seed_data = [
        {
            "text": f"What is the SI unit of force?",
            "options": ["Newton", "Joule", "Pascal", "Watt"],
            "correct": "Newton",
            "explanation": "Newton (N) is the SI unit of force, defined as 1 kg·m/s².",
            "subject": default_subj,
            "difficulty": Difficulty.easy
        },
        {
            "text": f"Which of the following is a scalar quantity?",
            "options": ["Speed", "Velocity", "Acceleration", "Force"],
            "correct": "Speed",
            "explanation": "Speed has only magnitude and no direction, making it a scalar quantity.",
            "subject": default_subj,
            "difficulty": Difficulty.easy
        },
        {
            "text": f"What is the acceleration due to gravity on the surface of the Earth?",
            "options": ["9.8 m/s²", "8.9 m/s²", "10.8 m/s²", "7.8 m/s²"],
            "correct": "9.8 m/s²",
            "explanation": "The standard acceleration due to gravity on Earth is approximately 9.8 m/s² (9.80665 m/s²).",
            "subject": default_subj,
            "difficulty": Difficulty.medium
        },
        {
            "text": f"According to Newton's Third Law, for every action there is:",
            "options": ["An equal and opposite reaction", "A greater reaction", "A smaller reaction", "No reaction"],
            "correct": "An equal and opposite reaction",
            "explanation": "Newton's Third Law states that every action force produces an equal and opposite reaction force simultaneously.",
            "subject": default_subj,
            "difficulty": Difficulty.medium
        },
        {
            "text": f"The rate of change of work done or energy transferred is called:",
            "options": ["Power", "Impulse", "Momentum", "Torque"],
            "correct": "Power",
            "explanation": "Power is defined as work done per unit time (P = W/t) with SI unit Watt (W).",
            "subject": default_subj,
            "difficulty": Difficulty.medium
        },
    ]

    new_objs = []
    for item in seed_data:
        q_obj = QuizQuestion(
            text=item["text"],
            options=item["options"],
            correct_answer=item["correct"],
            explanation=item["explanation"],
            question_type="mcq",
            subject=item["subject"],
            exam_tag=clean_exam or "General",
            grade_or_tag=grade_or_tag or "Class 12",
            difficulty=item["difficulty"],
            status=QuestionStatus.live,
            generated_at=datetime.now(timezone.utc),
        )
        db.add(q_obj)
        new_objs.append(q_obj)

    try:
        db.commit()
        for q in new_objs:
            db.refresh(q)
        return new_objs
    except Exception as e:
        db.rollback()
        logger.warning(f"Error seeding fallback questions: {e}")
        return []


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
