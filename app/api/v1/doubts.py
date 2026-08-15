"""Doubts & OCR router — AI Doubt Solver and OCR camera text extraction."""
import base64
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
    if not body.question_text or len(body.question_text.strip()) < 5:
        raise HTTPException(status_code=422, detail="Question text is too short")
    steps, final_answer, subject, key_concepts, related_topics = solve_doubt_intelligently(body.question_text, body.subject)
    doubt = Doubt(
        user_id=current_user.id, question_text=body.question_text.strip(), subject=subject,
        step_by_step_explanation=[{"step": s.step, "title": s.title, "content": s.content} for s in steps],
        final_answer=final_answer, key_concepts=key_concepts, related_topics=related_topics, is_bookmarked=False,
    )
    db.add(doubt); db.commit(); db.refresh(doubt)
    return DoubtSolveOut(doubt_id=doubt.id, question_text=doubt.question_text, subject=doubt.subject,
        steps=steps, final_answer=final_answer, key_concepts=key_concepts, related_topics=related_topics)


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


@router.post("/ocr/extract", response_model=OcrExtractOut)
async def ocr_extract(body: OcrExtractIn, current_user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    if not body.image_base64:
        raise HTTPException(status_code=422, detail="image_base64 is required")
    try:
        base64.b64decode(body.image_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid base64 image data")
    # Production: call Google Vision / Gemini Vision API here
    return OcrExtractOut(
        extracted_text="A stone is dropped from the top of a tower 100m high. Calculate the time to reach the ground (g = 10 m/s²).",
        detected_subject="Physics", confidence=0.91,
    )
