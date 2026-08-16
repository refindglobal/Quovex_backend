"""Quiz router - adaptive quiz sessions, scoring, ad mechanics."""
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import User, UserSubjectProficiency, UserTopicProgress, Topic, QuizQuestion, QuizSession, QuizAnswer, QuestionStatus, Difficulty
from app.schemas import (
    QuizStartIn, QuizStartOut, QuizQuestionOut,
    QuizAnswerIn, QuizAnswerOut,
    QuizCompleteOut, QuizAdDoubleIn, QuizAdDoubleOut,
    SubjectProgressOut, TopicQuizIn, TopicQuizOut, DailyQuizOut,
)
from app.services.quiz_service import (
    select_questions, check_answer, count_consecutive_correct,
    calculate_answer_points, update_proficiency,
)
from app.services.notification_service import send_rank_change
from app.services.leaderboard_service import get_user_rank

router = APIRouter(prefix="/quiz", tags=["quiz"])
logger = logging.getLogger(__name__)


def _get_quiz_session(db: DBSession, session_id: UUID, user_id) -> QuizSession:
    s = db.query(QuizSession).filter(
        QuizSession.id == session_id,
        QuizSession.user_id == user_id,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Quiz session not found")
    return s


@router.post("/start", response_model=QuizStartOut)
async def start_quiz(
    body: QuizStartIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    grade_or_tag = body.grade_or_tag or (current_user.class_or_year if current_user.class_or_year else body.exam_tag)

    questions = select_questions(
        db, current_user, body.subject, body.exam_tag,
        body.difficulty, body.question_count, grade_or_tag,
    )
    if not questions:
        # On-demand fresh question generation via Cerebras / Groq
        try:
            from app.tasks.question_generation import _call_cerebras, _pick_api_key
            from app.models import QuestionType, Difficulty
            api_key = _pick_api_key()
            tag = body.exam_tag or grade_or_tag or "General"
            subj = body.subject or "General"
            diff_str = str(body.difficulty).lower()
            diff_val = diff_str if diff_str in ("easy", "medium", "hard") else "medium"
            count = body.question_count or 5
            raw_qs = _call_cerebras(api_key, subj, tag, diff_val, count)
            for q_data in raw_qs:
                if q_data.get("text") and q_data.get("correct_answer"):
                    q_obj = QuizQuestion(
                        text=q_data.get("text", ""),
                        options=q_data.get("options", []),
                        correct_answer=q_data.get("correct_answer", ""),
                        explanation=q_data.get("explanation"),
                        question_type=QuestionType.mcq,
                        subject=subj,
                        exam_tag=body.exam_tag,
                        grade_or_tag=grade_or_tag,
                        difficulty=Difficulty[diff_val],
                        status=QuestionStatus.live,
                        generated_at=datetime.now(timezone.utc),
                    )
                    db.add(q_obj)
            db.commit()
            questions = select_questions(
                db, current_user, body.subject, body.exam_tag,
                body.difficulty, body.question_count, grade_or_tag,
            )
        except Exception as e:
            logger.warning(f"On-demand fresh question generation: {e}")

    if not questions:
        raise HTTPException(status_code=404, detail="No questions available for selected criteria")

    quiz_session = QuizSession(
        user_id=current_user.id,
        subject=body.subject,
        exam_tag=body.exam_tag,
        grade_or_tag=grade_or_tag,
        topic_id=body.topic_id,
        difficulty_mode=body.difficulty,
        question_ids=[q.id for q in questions],
        total_questions=len(questions),
        start_time=datetime.now(timezone.utc),
    )
    db.add(quiz_session)
    db.commit()
    db.refresh(quiz_session)

    return QuizStartOut(
        quiz_session_id=quiz_session.id,
        questions=[QuizQuestionOut.model_validate(q) for q in questions],
        grade_or_tag=grade_or_tag,
        started_at=quiz_session.start_time,
    )


@router.post("/answer", response_model=QuizAnswerOut)
async def submit_answer(
    body: QuizAnswerIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    quiz_session = _get_quiz_session(db, body.quiz_session_id, current_user.id)
    question = db.query(QuizQuestion).filter(QuizQuestion.id == body.question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    is_correct = check_answer(question, body.selected_answer)
    consecutive = count_consecutive_correct(db, quiz_session.id)
    points = calculate_answer_points(is_correct, body.response_time_ms, consecutive)

    answer = QuizAnswer(
        quiz_session_id=quiz_session.id,
        question_id=question.id,
        selected_answer=body.selected_answer,
        is_correct=is_correct,
        response_time_ms=body.response_time_ms,
        points_awarded=points,
        counts_toward_verified_score=True,
    )
    db.add(answer)

    if is_correct:
        quiz_session.total_correct += 1
        quiz_session.points_earned += points
        quiz_session.verified_quiz_score_earned += points

    db.commit()

    return QuizAnswerOut(
        is_correct=is_correct,
        correct_answer=question.correct_answer,
        explanation=question.explanation,
        points_awarded=points,
    )


@router.post("/complete/{quiz_session_id}", response_model=QuizCompleteOut)
async def complete_quiz(
    quiz_session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    quiz_session = _get_quiz_session(db, quiz_session_id, current_user.id)
    if quiz_session.is_complete:
        raise HTTPException(status_code=400, detail="Quiz already completed")

    quiz_session.end_time = datetime.now(timezone.utc)
    quiz_session.is_complete = True

    current_user.quiz_points_total += quiz_session.points_earned
    current_user.verified_quiz_score += quiz_session.verified_quiz_score_earned

    if quiz_session.subject:
        update_proficiency(db, current_user, quiz_session)

    if quiz_session.topic_id and quiz_session.total_questions > 0:
        topic_progress = (
            db.query(UserTopicProgress)
            .filter(
                UserTopicProgress.user_id == current_user.id,
                UserTopicProgress.topic_id == quiz_session.topic_id,
            )
            .first()
        )
        if not topic_progress:
            topic_progress = UserTopicProgress(
                user_id=current_user.id,
                topic_id=quiz_session.topic_id,
            )
            db.add(topic_progress)
        topic_progress.questions_answered += quiz_session.total_questions
        topic_progress.correct += quiz_session.total_correct
        topic_progress.accuracy = (
            topic_progress.correct / topic_progress.questions_answered
            if topic_progress.questions_answered > 0 else 0.0
        )

    db.commit()
    db.refresh(quiz_session)

    for track in ("quiz", "overall"):
        rank_data = get_user_rank(db, current_user.id, track, "global", "month")
        if not rank_data:
            continue
        new_rank = rank_data["rank"]
        last_ranks = current_user.last_known_ranks or {}
        old_rank = last_ranks.get(track)
        if old_rank is not None and old_rank != new_rank:
            send_rank_change(db, current_user, old_rank, new_rank, track)
        last_ranks[track] = new_rank
        current_user.last_known_ranks = last_ranks
    db.commit()

    accuracy = (
        quiz_session.total_correct / quiz_session.total_questions * 100
        if quiz_session.total_questions > 0 else 0
    )

    return QuizCompleteOut(
        quiz_session_id=quiz_session.id,
        total_correct=quiz_session.total_correct,
        total_questions=quiz_session.total_questions,
        accuracy_percent=round(accuracy, 1),
        points_earned=quiz_session.points_earned,
        verified_quiz_score_earned=quiz_session.verified_quiz_score_earned,
        grade_or_tag=quiz_session.grade_or_tag,
        ad_double_available=not quiz_session.ad_doubled,
        bonus_questions_available=not quiz_session.bonus_questions_added,
        message=f"Quiz complete! {quiz_session.total_correct}/{quiz_session.total_questions} correct",
    )


@router.post("/ad-double", response_model=QuizAdDoubleOut)
async def ad_double_quiz(
    body: QuizAdDoubleIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    quiz_session = _get_quiz_session(db, body.quiz_session_id, current_user.id)
    if quiz_session.ad_doubled:
        return QuizAdDoubleOut(
            points_earned=quiz_session.points_earned, success=False,
            message="Already doubled for this session",
        )

    extra = quiz_session.points_earned
    quiz_session.points_earned += extra
    quiz_session.ad_doubled = True
    current_user.quiz_points_total += extra
    db.commit()

    return QuizAdDoubleOut(
        points_earned=quiz_session.points_earned,
        success=True,
        message="Quiz points doubled! (Leaderboard score unchanged)",
    )


@router.get("/subject-progress", response_model=list[SubjectProgressOut])
async def get_subject_progress(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    proficiencies = (
        db.query(UserSubjectProficiency)
        .filter(UserSubjectProficiency.user_id == current_user.id)
        .all()
    )
    if not proficiencies:
        subjects = ["Physics", "Chemistry", "Biology", "Mathematics", "History"]
        return [SubjectProgressOut(subject=s) for s in subjects]

    return [
        SubjectProgressOut(
            subject=p.subject,
            accuracy=p.rolling_accuracy_score,
            questions_answered=p.total_questions_answered,
        )
        for p in proficiencies
    ]


@router.get("/daily", response_model=DailyQuizOut)
async def get_daily_quiz(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the daily quiz for user's primary subject and exam target."""
    subject = current_user.primary_subject or "Physics"
    exam_tag = current_user.exam_target or "General Study"
    grade_or_tag = current_user.class_or_year or exam_tag

    questions = select_questions(
        db, current_user, subject, exam_tag, "adaptive", 5, grade_or_tag
    )
    if not questions:
        try:
            from app.tasks.question_generation import _call_cerebras, _pick_api_key
            from app.models import UserSubjectProficiency
            api_key = _pick_api_key()
            # Layer 2 FIX: use adaptive difficulty for AI generation too
            prof = (
                db.query(UserSubjectProficiency)
                .filter(
                    UserSubjectProficiency.user_id == current_user.id,
                    UserSubjectProficiency.subject == subject,
                )
                .first()
            )
            accuracy = prof.rolling_accuracy_score if prof else 0.5
            if accuracy < 0.4:
                gen_diff = "easy"
            elif accuracy < 0.7:
                gen_diff = "medium"
            else:
                gen_diff = "hard"
            raw_qs = _call_cerebras(api_key, subject, exam_tag, gen_diff, 5)
            for q_data in raw_qs:
                if q_data.get("text") and q_data.get("correct_answer"):
                    q_obj = QuizQuestion(
                        text=q_data.get("text", ""),
                        options=q_data.get("options", []),
                        correct_answer=q_data.get("correct_answer", ""),
                        explanation=q_data.get("explanation"),
                        question_type="mcq",
                        subject=subject,
                        exam_tag=exam_tag,
                        grade_or_tag=grade_or_tag,
                        difficulty=Difficulty[gen_diff],
                        status=QuestionStatus.live,
                        generated_at=datetime.now(timezone.utc),
                    )
                    db.add(q_obj)
            db.commit()
            questions = select_questions(
                db, current_user, subject, exam_tag, "adaptive", 5, grade_or_tag
            )
        except Exception as e:
            logger.warning(f"Failed to generate daily quiz: {e}")


    now = datetime.now(timezone.utc)
    session_obj = QuizSession(
        user_id=current_user.id,
        subject=subject,
        exam_tag=exam_tag,
        grade_or_tag=grade_or_tag,
        difficulty_mode=Difficulty.adaptive,
        question_ids=[str(q.id) for q in questions],
        start_time=now,
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)

    return DailyQuizOut(
        quiz_id=str(session_obj.id),
        questions=[QuizQuestionOut.model_validate(q) for q in questions],
        date=now.strftime("%Y-%m-%d"),
        expires_at=(now + timedelta(days=1)).isoformat(),
    )


@router.post("/topic", response_model=TopicQuizOut)
async def generate_topic_quiz(
    body: TopicQuizIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Generate on-demand quiz questions for a specific topic."""
    subject = body.subject or current_user.primary_subject or "Physics"
    exam_tag = body.exam_tag or current_user.exam_target or "General Study"
    grade_or_tag = current_user.class_or_year or exam_tag
    count = body.question_count or 5

    # Layer 2 FIX: resolve difficulty adaptively from user proficiency
    diff_requested = (body.difficulty or "adaptive").lower()
    if diff_requested == "adaptive":
        from app.models import UserSubjectProficiency
        prof = (
            db.query(UserSubjectProficiency)
            .filter(
                UserSubjectProficiency.user_id == current_user.id,
                UserSubjectProficiency.subject == subject,
            )
            .first()
        )
        accuracy = prof.rolling_accuracy_score if prof else 0.5
        if accuracy < 0.4:
            diff_val = "easy"
        elif accuracy < 0.7:
            diff_val = "medium"
        else:
            diff_val = "hard"
    else:
        diff_val = diff_requested if diff_requested in ("easy", "medium", "hard") else "medium"

    # Layer 1 FIX: select questions filtered by grade AND subject
    questions = select_questions(
        db, current_user, subject, exam_tag, diff_val, count, grade_or_tag
    )
    if not questions or len(questions) < count:
        try:
            from app.tasks.question_generation import _call_cerebras, _pick_api_key
            api_key = _pick_api_key()
            # Include topic in generation for specificity
            topic_subject = f"{subject} - {body.topic}"
            raw_qs = _call_cerebras(api_key, topic_subject, exam_tag, diff_val, count)
            for q_data in raw_qs:
                if q_data.get("text") and q_data.get("correct_answer"):
                    q_obj = QuizQuestion(
                        text=q_data.get("text", ""),
                        options=q_data.get("options", []),
                        correct_answer=q_data.get("correct_answer", ""),
                        explanation=q_data.get("explanation"),
                        question_type="mcq",
                        subject=subject,
                        exam_tag=exam_tag,
                        grade_or_tag=grade_or_tag,  # Layer 1 FIX: tag generated questions with user's grade
                        difficulty=Difficulty[diff_val],
                        status=QuestionStatus.live,
                        generated_at=datetime.now(timezone.utc),
                    )
                    db.add(q_obj)
            db.commit()
            # Re-select with full grade filter now that questions are stored
            questions = select_questions(
                db, current_user, subject, exam_tag, diff_val, count, grade_or_tag
            )
        except Exception as e:
            logger.warning(f"Failed to generate topic quiz: {e}")

    now = datetime.now(timezone.utc)
    session_obj = QuizSession(
        user_id=current_user.id,
        subject=subject,
        exam_tag=exam_tag,
        grade_or_tag=grade_or_tag,
        difficulty_mode=Difficulty[diff_val],
        question_ids=[str(q.id) for q in questions],
        start_time=now,
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)

    return TopicQuizOut(
        quiz_id=str(session_obj.id),
        questions=[QuizQuestionOut.model_validate(q) for q in questions],
        topic=body.topic,
        generated_at=now.isoformat(),
    )

