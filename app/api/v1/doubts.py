"""Doubts & OCR router — AI Doubt Solver and OCR camera text extraction."""
import base64
import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import User, Doubt
from app.schemas import (
    DoubtSolveIn, DoubtSolveOut, DoubtStepOut,
    DoubtHistoryOut, DoubtBookmarkIn,
    OcrExtractIn, OcrExtractOut,
)

router = APIRouter(tags=["learn"])

SUBJECT_HINTS = {
    "physics": ["force", "velocity", "acceleration", "energy", "momentum", "newton", "gravity", "mass", "charge", "current", "wave", "optics"],
    "mathematics": ["integral", "derivative", "limit", "matrix", "equation", "polynomial", "proof", "theorem", "function", "vector", "calculus"],
    "chemistry": ["element", "compound", "reaction", "mole", "bond", "orbital", "acid", "base", "equilibrium", "enthalpy", "periodic"],
    "biology": ["cell", "dna", "rna", "protein", "organism", "evolution", "photosynthesis", "respiration", "neuron", "chromosome"],
}


def _detect_subject(text: str, hint: Optional[str] = None) -> str:
    if hint and hint.lower() not in ("general", ""):
        return hint.capitalize()
    low = text.lower()
    scores = {subject: sum(1 for kw in keywords if kw in low) for subject, keywords in SUBJECT_HINTS.items()}
    best = max(scores, key=scores.get)
    return best.capitalize() if scores[best] > 0 else "General"


def _generate_doubt_solution(question: str, subject: str):
    q = question.strip()
    subject_cap = subject.capitalize()

    steps = [
        DoubtStepOut(step=1, title="Understand the Problem",
            content=f'Read carefully: "{q[:200]}{"..." if len(q) > 200 else ""}"\n\nIdentify what is given and what is asked.'),
        DoubtStepOut(step=2, title="Recall Key Concepts",
            content=f"This is a {subject_cap} problem. Recall the relevant formulas, laws, or theorems that apply."),
        DoubtStepOut(step=3, title="Set Up the Solution",
            content="Write the appropriate formula. Substitute known values. Ensure all units are consistent."),
        DoubtStepOut(step=4, title="Solve Step-by-Step",
            content="Work through the mathematics carefully. Show each algebraic step. Simplify progressively."),
        DoubtStepOut(step=5, title="Verify & Interpret",
            content="Check the answer by substituting back. Ensure the result is physically/logically reasonable."),
    ]

    concepts_map = {
        "Physics": ["F = ma", "v = u + at", "Work-Energy Theorem", "Conservation of Momentum", "Ohm's Law V=IR"],
        "Mathematics": ["Quadratic Formula", "Chain Rule", "Integration by Parts", "Pythagoras Theorem", "BODMAS"],
        "Chemistry": ["PV = nRT", "Avogadro's Number (6.022×10²³)", "Law of Conservation of Mass", "Le Chatelier's Principle", "Molarity = moles/volume"],
        "Biology": ["Central Dogma: DNA→RNA→Protein", "Cell Theory", "Law of Natural Selection", "ATP = Energy Currency", "Mendelian Genetics"],
        "General": ["Define all variables", "Break into smaller steps", "Check all units", "Estimate first"],
    }
    related_map = {
        "Physics": ["Kinematics", "Work, Energy & Power", "Waves & Optics", "Electrostatics", "Modern Physics"],
        "Mathematics": ["Algebra", "Calculus", "Trigonometry", "Coordinate Geometry", "Statistics"],
        "Chemistry": ["Atomic Structure", "Chemical Bonding", "Thermodynamics", "Equilibrium", "Electrochemistry"],
        "Biology": ["Cell Biology", "Genetics & Evolution", "Human Physiology", "Plant Biology", "Ecology"],
        "General": ["Problem Solving", "Analytical Reasoning", "Logical Deduction"],
    }

    final_answer = (
        f"Follow the steps above using the relevant {subject_cap} formulas to arrive at the precise answer. "
        f"Verify using dimensional analysis or substitution."
    )
    return steps, final_answer, concepts_map.get(subject_cap, concepts_map["General"]), related_map.get(subject_cap, related_map["General"])


from app.services.doubt_solver_engine import solve_doubt_intelligently, detect_subject


@router.post("/doubts/solve", response_model=DoubtSolveOut)
async def solve_doubt(body: DoubtSolveIn, current_user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    if not body.question_text or len(body.question_text.strip()) < 2:
        raise HTTPException(status_code=422, detail="Question text must be at least 2 characters")
    subject = detect_subject(body.question_text, body.subject)
    
    user_context = body.user_context
    if not user_context and current_user:
        parts = []
        if current_user.display_name or current_user.full_name:
            parts.append(f"Student: {current_user.display_name or current_user.full_name}")
        if current_user.class_or_year:
            parts.append(f"Grade/Level: {current_user.class_or_year}")
        if current_user.education_type:
            parts.append(f"Exam: {current_user.education_type}")
        if current_user.primary_subject:
            parts.append(f"Subject: {current_user.primary_subject}")
        user_context = " | ".join(parts)

    steps, final_answer, key_concepts, related_topics, question_type, confidence, confidence_label = solve_doubt_intelligently(
        body.question_text, body.subject, body.follow_up_action, body.chat_history, user_context=user_context
    )
    doubt_id = str(uuid.uuid4())
    try:
        doubt = Doubt(
            id=uuid.UUID(doubt_id),
            user_id=current_user.id,
            question_text=body.question_text.strip(),
            subject=subject,
            step_by_step_explanation=[{"step": s.step, "title": s.title, "content": s.content} for s in steps],
            final_answer=final_answer,
            key_concepts=key_concepts,
            related_topics=related_topics,
            is_bookmarked=False,
        )
        db.add(doubt)
        db.commit()
        db.refresh(doubt)
        doubt_id = str(doubt.id)
    except Exception:
        db.rollback()

    return DoubtSolveOut(
        doubt_id=doubt_id,
        question_text=body.question_text.strip(),
        subject=subject,
        question_type=question_type,
        confidence=confidence,
        confidence_label=confidence_label,
        steps=steps,
        final_answer=final_answer,
        key_concepts=key_concepts,
        related_topics=related_topics
    )


@router.get("/doubts/history", response_model=list[DoubtHistoryOut])
async def get_doubt_history(subject: Optional[str] = None, bookmarked_only: bool = False, limit: int = 20,
    current_user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    q = db.query(Doubt).filter(Doubt.user_id == current_user.id)
    if subject:
        q = q.filter(Doubt.subject.ilike(f"%{subject}%"))
    if bookmarked_only:
        q = q.filter(Doubt.is_bookmarked == True)
    doubts = q.order_by(Doubt.created_at.desc()).limit(limit).all()
    return [DoubtHistoryOut(doubt_id=d.id, question_text=d.question_text, subject=d.subject,
        final_answer=d.final_answer, key_concepts=d.key_concepts or [], is_bookmarked=d.is_bookmarked,
        created_at=d.created_at) for d in doubts]


@router.post("/doubts/bookmark")
async def toggle_bookmark(body: DoubtBookmarkIn, current_user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    doubt = db.query(Doubt).filter(Doubt.id == body.doubt_id, Doubt.user_id == current_user.id).first()
    if not doubt:
        raise HTTPException(status_code=404, detail="Doubt not found")
    doubt.is_bookmarked = body.is_bookmarked
    db.commit()
    return {"success": True, "is_bookmarked": doubt.is_bookmarked}


from app.services.doubt_solver_engine import solve_doubt_from_image


@router.post("/doubts/image-solve")
async def solve_doubt_from_image_endpoint(
    body: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Stateless vision endpoint.
    Accepts a base64-encoded image of a textbook question/problem/diagram.
    Sends it directly to Cerebras gemma-4-31b (FREE vision model).
    Returns the full answer + key concepts.
    The image is NEVER saved — it flows through memory only.
    """
    image_base64 = body.get("image_base64", "").strip()
    image_mime = body.get("image_mime", "image/jpeg")
    subject_hint = body.get("subject", "")

    if not image_base64:
        raise HTTPException(status_code=422, detail="image_base64 is required")

    # Validate base64
    try:
        import base64 as _b64
        _b64.b64decode(image_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid base64 image data")

    # Process through vision model — no DB write, no file write
    answer, key_concepts, related_topics = solve_doubt_from_image(
        image_base64=image_base64,
        image_mime=image_mime,
        subject_hint=subject_hint,
    )

    return {
        "answer": answer,
        "key_concepts": key_concepts,
        "related_topics": related_topics,
        "model": "gemma-4-31b",
        "image_saved": False,
    }

