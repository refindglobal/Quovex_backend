import sys
sys.path.insert(0, r"c:\Users\Testbook\Downloads\study\studytimer_backend")
import traceback
from app.db.session import SessionLocal
from app.models import User, Doubt
from app.services.doubt_solver_engine import solve_doubt_intelligently, detect_subject

try:
    db = SessionLocal()
    user = db.query(User).first()
    print("User found:", user.email, user.id)
    
    question = "Explain Speed of Light in detail with formulas and examples."
    subject = detect_subject(question, "General")
    print("Subject detected:", subject)
    
    steps, final_answer, key_concepts, related_topics, question_type, confidence, confidence_label = solve_doubt_intelligently(
        question, "General", None
    )
    print("Solved successfully!")
    print("Steps count:", len(steps))
    print("Final answer preview:", final_answer[:60])
    
    doubt = Doubt(
        user_id=user.id,
        question_text=question,
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
    print("Saved doubt to DB:", doubt.id)
except Exception as e:
    print("ERROR OCCURRED:")
    traceback.print_exc()
