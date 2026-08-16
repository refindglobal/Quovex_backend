"""Quiz question generation using Cerebras API with key rotation."""
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import List

import httpx
from app.config import settings
from app.db.session import SessionLocal
from app.models import QuizQuestion, QuestionType, Difficulty, QuestionStatus
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

SUBJECTS_EXAM_TAGS = [
    ("Physics", "JEE"), ("Chemistry", "JEE"), ("Mathematics", "JEE"),
    ("Biology", "NEET"), ("Physics", "NEET"), ("Chemistry", "NEET"),
    ("History", "UPSC"), ("Geography", "UPSC"), ("Polity", "UPSC"),
    ("Mathematics", "SAT"), ("English", "SAT"),
    ("General Science", "General Study"),
]


def _get_grade_subject_combos() -> list[tuple[str, str]]:
    """Read (grade_or_tag, subject_name) pairs from grade_subjects table."""
    try:
        from app.db.session import SessionLocal
        from app.models import GradeSubject
        db = SessionLocal()
        rows = db.query(GradeSubject.grade_or_tag, GradeSubject.subject_name).distinct().all()
        db.close()
        return [(r.subject_name, r.grade_or_tag) for r in rows]
    except Exception:
        return []

GENERATION_PROMPT = """Generate {count} high-quality, human-readable quiz questions for subject: {subject}, exam: {exam_tag}, difficulty: {difficulty}.

Context: {context_note}

Return ONLY a valid JSON array. Each object must have:
- "text": Clear, engaging, and well-written question text
- "options": Array of exactly 4 distinct, clean answer strings
- "correct_answer": The exact matching correct answer string from the options array
- "explanation": Clear, human-friendly explanation explaining WHY the answer is correct (2-3 sentences)
- "question_type": "mcq"

Formatting & Readability Rules:
1. Highly readable: Formulate clear, concise questions in standard textbook English.
2. Clean Math & Science: Use clean Unicode symbols (e.g., x², y³, √x, π, θ, α, β, Δ, CO₂, H₂SO₄, 1/2) instead of raw LaTeX markup like \\frac{{}}{{}} or $...$.
3. Clean options: Do NOT prefix options with "A)", "B)", "1.", "Option A:". Just provide the clean answer text.
4. Exact match: "correct_answer" MUST be character-for-character identical to one of the 4 strings in "options".
5. Factually verified: Every question, answer, and explanation must be 100% factually accurate and relevant to {exam_tag}.
"""


def _grade_to_age(grade: str) -> str:
    mapping = {
        "Class 1": "6-7", "Class 2": "7-8", "Class 3": "8-9",
        "Class 4": "9-10", "Class 5": "10-11", "Class 6": "11-12",
        "Class 7": "12-13", "Class 8": "13-14", "Class 9": "14-15",
        "Class 10": "15-16", "Class 11": "16-17", "Class 12": "17-18",
    }
    return mapping.get(grade, "school-age")


def _pick_api_key() -> str:
    keys_str = settings.CEREBRAS_API_KEYS or settings.CEREBRAS_API_KEY
    if not keys_str:
        return ""
    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    return random.choice(keys) if keys else ""


def _pick_groq_key() -> str:
    keys_str = settings.GROQ_API_KEYS or settings.GROQ_API_KEY
    if not keys_str:
        return ""
    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    return random.choice(keys) if keys else ""


def _call_cerebras(api_key: str, subject: str, exam_tag: str, difficulty: str, count: int) -> List[dict]:
    """Call Cerebras API for question generation with Groq fallback on failure."""
    is_school_grade = exam_tag.startswith("Class ") or "CLASS " in exam_tag.upper()
    context_note = (
        f"CRITICAL CONSTRAINT: These questions are STRICTLY for {exam_tag} students (age ~{_grade_to_age(exam_tag)}). "
        f"Only use syllabus topics from standard {exam_tag} curriculum. "
        f"DO NOT include advanced Class 11, Class 12, JEE, or college concepts (e.g. NO calculus, complex integrals, or quantum mechanics). "
        f"Keep language and concepts strictly at {exam_tag} level."
        if is_school_grade
        else f"These questions are for {exam_tag} competitive exam preparation."
    )
    prompt = GENERATION_PROMPT.format(
        count=count, subject=subject, exam_tag=exam_tag, difficulty=difficulty, context_note=context_note
    )

    last_exc = None
    # 1. Try Cerebras
    for attempt in range(2):
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
                        {"role": "system", "content": "You are an expert exam question writer. Return only valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 4096,
                },
                timeout=30,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            start = content.find("[")
            end = content.rfind("]") + 1
            if start != -1 and end > 0:
                return json.loads(content[start:end])
        except Exception as e:
            last_exc = e
            api_key = _pick_api_key()
            time.sleep(0.5)

    # 2. Fallback to Groq API
    groq_key = _pick_groq_key()
    if groq_key:
        try:
            logger.info("Falling back to Groq for question generation")
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are an expert exam question writer. Return only valid JSON array."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 4096,
                },
                timeout=30,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            start = content.find("[")
            end = content.rfind("]") + 1
            if start != -1 and end > 0:
                return json.loads(content[start:end])
        except Exception as e:
            last_exc = e

    if last_exc:
        raise last_exc
    raise ValueError("No AI API keys configured or available")
def generate_quiz_questions(subject: str = None, exam_tag: str = None, grade_or_tag: str = None, count_per_combo: int = 20):
    """Generate quiz questions via Cerebras API and store in DB as live."""
    api_key = _pick_api_key()
    if not api_key:
        logger.warning("No Cerebras API keys configured, skipping generation")
        return

    # Build combos
    combos: list[tuple[str, str, str | None, str | None]]
    if subject and (exam_tag or grade_or_tag):
        # Specific combo requested
        tag_label = exam_tag or grade_or_tag
        combos = [(subject, tag_label, exam_tag, grade_or_tag)]
    else:
        # All exam-tag combos + all grade-subject combos
        exam_combos: list[tuple[str, str, str | None, str | None]] = [
            (s, t, t, None) for s, t in SUBJECTS_EXAM_TAGS
        ]
        grade_combos: list[tuple[str, str, str | None, str | None]] = [
            (subject_name, grade_tag, None, grade_tag)
            for subject_name, grade_tag in _get_grade_subject_combos()
        ]
        seen = set()
        combos = []
        for c in exam_combos + grade_combos:
            key = (c[0], c[1])
            if key not in seen:
                seen.add(key)
                combos.append(c)

    db = SessionLocal()
    total_generated = 0

    try:
        for subj, label, e_tag, g_tag in combos:
            for diff in [Difficulty.easy, Difficulty.medium, Difficulty.hard]:
                try:
                    questions = _call_cerebras(api_key, subj, label, diff.value, count_per_combo)
                    for q_data in questions:
                        if not q_data.get("text") or not q_data.get("correct_answer"):
                            logger.warning(f"Skipping malformed question from Cerebras: {q_data}")
                            continue
                        q = QuizQuestion(
                            text=q_data.get("text", ""),
                            options=q_data.get("options", []),
                            correct_answer=q_data.get("correct_answer", ""),
                            explanation=q_data.get("explanation"),
                            question_type=QuestionType.mcq,
                            subject=subj,
                            exam_tag=e_tag,
                            grade_or_tag=g_tag,
                            difficulty=diff,
                            status=QuestionStatus.live,
                            generated_at=datetime.now(timezone.utc),
                        )
                        db.add(q)
                        total_generated += 1
                    db.commit()
                    logger.info(f"Generated {len(questions)} questions for {subj}/{label}/{diff.value}")
                except Exception as e:
                    logger.error(f"Failed to generate questions for {subj}/{label}/{diff.value}: {e}")
                    db.rollback()
    finally:
        db.close()

    return f"Generated {total_generated} questions total"

