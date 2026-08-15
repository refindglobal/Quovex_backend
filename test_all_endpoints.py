"""Comprehensive endpoint verification test suite for Quovex backend."""
import sys
import os
from unittest.mock import patch

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# Remove existing test DB if any
test_db_file = os.path.abspath("test_suite.db")
if os.path.exists(test_db_file):
    try:
        os.remove(test_db_file)
    except Exception:
        pass

# Set environment
os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = f"sqlite:///{test_db_file}"

import app.models
from app.main import app as fastapi_app
from app.db.session import Base, engine

# Create all tables in memory after app & models are fully imported
Base.metadata.create_all(bind=engine)

from fastapi.testclient import TestClient

client = TestClient(fastapi_app)

def run_tests():
    print("=" * 60)
    print("RUNNING QUOVEX BACKEND ENDPOINT VERIFICATION SUITE")
    print("=" * 60)
    
    passed = 0
    total = 0

    def check(name, response, expected_status=200):
        nonlocal passed, total
        total += 1
        if response.status_code == expected_status:
            print(f"[PASS] {name} ({response.status_code})")
            passed += 1
            return True
        else:
            print(f"[FAIL] {name} (Expected {expected_status}, got {response.status_code}): {response.text}")
            return False

    # 1. Health Check
    res = client.get("/health")
    check("GET /health", res)

    # 2. Auth Flow: Send OTP & Verify OTP
    test_email = "student_test@quovex.app"
    
    with patch("app.api.v1.auth.generate_otp", return_value="123456"):
        res = client.post("/api/v1/auth/send-otp", json={"email": test_email})
        check("POST /api/v1/auth/send-otp", res)

    with patch("app.api.v1.auth.verify_otp", return_value=True):
        res = client.post("/api/v1/auth/verify-otp", json={"email": test_email, "otp": "123456"})
        check("POST /api/v1/auth/verify-otp", res)
    
    auth_data = res.json()
    token = auth_data.get("access_token", "")
    headers = {"Authorization": f"Bearer {token}"}
    print(f"   -> Obtained JWT Token: {token[:20]}...")

    # 3. User Profile / Home Page APIs
    res = client.get("/api/v1/users/me", headers=headers)
    check("GET /api/v1/users/me", res)

    res = client.get("/api/v1/sessions/today", headers=headers)
    check("GET /api/v1/sessions/today", res)

    res = client.get("/api/v1/streak", headers=headers)
    check("GET /api/v1/streak", res)

    res = client.get("/api/v1/wallet/", headers=headers)
    check("GET /api/v1/wallet/", res)

    # 4. Onboarding & Profile Setup Flow
    profile_update = {
        "full_name": "Test Student",
        "display_name": "ProStudent",
        "education_type": "High School",
        "exam_target": "JEE Main & Advanced",
        "study_goal": "Crack JEE Top 100",
        "daily_target_hours": 4.0,
        "study_time_preference": "Night Owl",
        "profile_complete": True
    }
    res = client.patch("/api/v1/users/me", json=profile_update, headers=headers)
    check("PATCH /api/v1/users/me (Onboarding Complete)", res)

    # Claim Welcome Gift
    res = client.post("/api/v1/users/me/gifts/welcome", headers=headers)
    check("POST /api/v1/users/me/gifts/welcome", res)

    # 5. Study Session Flow
    res = client.post("/api/v1/sessions/start", json={"mode": "focus", "subject_tag": "Physics"}, headers=headers)
    check("POST /api/v1/sessions/start", res)
    session_id = res.json().get("session_id")

    res = client.post(f"/api/v1/sessions/{session_id}/end", json={"session_id": session_id}, headers=headers)
    check(f"POST /api/v1/sessions/{session_id}/end", res)

    # 6. History, Analytics, Quiz
    res = client.get("/api/v1/study-history/", headers=headers)
    check("GET /api/v1/study-history/", res)

    res = client.get("/api/v1/study-history/analytics", headers=headers)
    check("GET /api/v1/study-history/analytics", res)

    res = client.get("/api/v1/study-history/verification-quiz?subject=Physics", headers=headers)
    check("GET /api/v1/study-history/verification-quiz", res)

    # 7. Live Study Rooms
    res = client.get("/api/v1/study-rooms/", headers=headers)
    check("GET /api/v1/study-rooms/", res)

    res = client.post("/api/v1/study-rooms/create", json={"name": "Physics Squad", "subject": "Physics", "privacy": "public"}, headers=headers)
    check("POST /api/v1/study-rooms/create", res)
    room_id = res.json().get("room_id")

    res = client.post(f"/api/v1/study-rooms/{room_id}/join", headers=headers)
    check(f"POST /api/v1/study-rooms/{room_id}/join", res)

    res = client.post(f"/api/v1/study-rooms/{room_id}/leave", headers=headers)
    check(f"POST /api/v1/study-rooms/{room_id}/leave", res)

    print("=" * 60)
    print(f"TEST SUMMARY: {passed}/{total} ENDPOINTS PASSED CLEANLY.")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
