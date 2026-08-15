"""Celery application and scheduled tasks."""
from celery import Celery
from celery.schedules import crontab
from app.config import settings

celery_app = Celery(
    "studytimer",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.midnight_reset",
        "app.tasks.monthly_leaderboard_freeze",
        "app.tasks.flagged_session_scanner",
        "app.tasks.daily_study_reminder_scan",
        "app.tasks.streak_risk_scan",
        "app.tasks.question_generation",
        "app.tasks.class_auto_advance",  # April 1 class advancement
        "app.tasks.kyc_reminder_scan",
        "app.tasks.weekly_accuracy_drop_scan",
        "app.tasks.report_generation",
    ],
)

celery_app.conf.beat_schedule = {
    # Social unlock reset at midnight (run every hour, logic checks per-user)
    "midnight-social-unlock-reset": {
        "task": "app.tasks.midnight_reset.reset_social_unlock",
        "schedule": crontab(minute=0),  # every hour
    },
    # Monthly freeze on last day of month at 23:55 UTC
    "monthly-leaderboard-freeze": {
        "task": "app.tasks.monthly_leaderboard_freeze.freeze_leaderboard",
        "schedule": crontab(minute=55, hour=23, day_of_month=28),
    },
    # Anti-cheat: daily flagged session scan at 2 AM UTC
    "flagged-session-scan": {
        "task": "app.tasks.flagged_session_scanner.scan_flagged_sessions",
        "schedule": crontab(minute=0, hour=2),
    },
    # Daily study reminders at 6 PM UTC
    "daily-study-reminder": {
        "task": "app.tasks.daily_study_reminder_scan.send_study_reminders",
        "schedule": crontab(minute=0, hour=18),
    },
    # Streak risk alerts at 8 PM UTC
    "streak-risk-scan": {
        "task": "app.tasks.streak_risk_scan.check_streak_risks",
        "schedule": crontab(minute=0, hour=20),
    },
    # ── April 1 auto-advance: school/college class year ──
    # Runs at 00:05 UTC on April 1st every year (after Indian academic year ends)
    "class-auto-advance": {
        "task": "app.tasks.class_auto_advance.advance_all_classes",
        "schedule": crontab(minute=5, hour=0, day_of_month=1, month_of_year=4),
    },
    # KYC reminder: runs daily at 12:00 UTC
    "kyc-reminder-scan": {
        "task": "app.tasks.kyc_reminder_scan.kyc_reminder_scan",
        "schedule": crontab(minute=0, hour=12),
    },
}

celery_app.conf.timezone = "UTC"

# BUG FIX: Without this setting Celery 5.x emits a CPendingDeprecationWarning
# every startup and the behavior will change in Celery 6.0.
# Setting it explicitly to True preserves the current retry-on-startup behavior.
celery_app.conf.broker_connection_retry_on_startup = True
