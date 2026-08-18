import json
from app.db.session import SessionLocal
from app.models import QuizQuestion

db = SessionLocal()
questions = db.query(QuizQuestion).order_by(QuizQuestion.generated_at.desc()).limit(5).all()
data = []
for q in questions:
    data.append({
        "id": str(q.id),
        "text": q.text,
        "options": q.options,
        "correct_answer": q.correct_answer
    })

with open("dump.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("Dumped to dump.json")
