from pydantic_settings import BaseSettings
from typing import List, Optional
import logging
import warnings

logger = logging.getLogger(__name__)

DEFAULT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    APP_NAME: str = "Quovex API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = DEFAULT_SECRET
    DATABASE_URL: str = "sqlite:///./studytimer.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    FIREBASE_PROJECT_ID: str = "quovex-84b14"
    FIREBASE_CREDENTIALS_PATH: str = "firebase-credentials.json"
    FIREBASE_SERVICE_ACCOUNT_JSON: Optional[str] = ""
    CEREBRAS_API_KEY: str = ""
    CEREBRAS_API_KEYS: str = ""
    CEREBRAS_MODEL: str = "gpt-oss-120b"
    GROQ_API_KEY: str = ""
    GROQ_API_KEYS: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    REWARD_BUDGET_CAP_PERCENT: int = 35
    BASE_POINTS_PER_HOUR: int = 100
    DIMINISHING_RETURNS_AFTER_HOURS: int = 6
    MAX_DAILY_HOURS_FLAG: int = 12
    SOCIAL_UNLOCK_MINUTES_PER_HOUR: int = 15
    SOCIAL_UNLOCK_AD_BONUS_MINUTES: int = 5
    SOCIAL_UNLOCK_AD_COOLDOWN_HOURS: int = 2
    APP_LOCK_MAX_CREDITS: int = 90
    APP_LOCK_CREDITS_PER_HOUR: int = 15
    APP_LOCK_UNLOCK_MINUTES: int = 15
    APP_LOCK_AD_UNLOCK_MINUTES: int = 5
    APP_LOCK_MAX_AD_UNLOCKS_PER_HOUR: int = 2
    EMAIL_HOST: str = ""
    EMAIL_PORT: int = 587
    EMAIL_USER: str = ""
    EMAIL_PASS: str = ""
    BREVO_API_KEY: str = ""
    QUIZ_SET_SIZE: int = 10
    QUIZ_QUESTION_TIME_LIMIT_SECONDS: int = 25
    MAX_QUIZ_ATTEMPTS_PER_SUBJECT_PER_DAY: int = 5
    MAX_DAILY_AD_DOUBLES: int = 2
    AD_EXTEND_MINUTES: int = 15
    AD_EXTEND_POINTS: int = 25
    REFERRAL_BONUS_SIGNUP: int = 100
    REFERRAL_BONUS_FIRST_SESSION: int = 50
    QUIZ_BASE_POINTS_PER_CORRECT: int = 10
    QUIZ_SPEED_BONUS_POINTS: int = 3
    QUIZ_STREAK_BONUS_POINTS: int = 2
    QUIZ_SPEED_BONUS_THRESHOLD_MS: int = 10000
    NOTIFICATION_MAX_DAILY_PUSHES: int = 7
    POINTS_DECAY_HALF_LIFE_MINUTES: int = 83
    POINTS_MIN_DECAY_FACTOR: float = 0.1

    SUPPORT_EMAIL: str = "supportquovex@gmail.com"
    FROM_EMAIL: str = "supportquovex@gmail.com"
    FIREBASE_CREDENTIALS_JSON: Optional[str] = ""

    UPLOAD_DIR: str = "./uploads"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

    def model_post_init(self, __context):
        # ── Fix Railway's postgres:// → postgresql:// (SQLAlchemy 2.x) ────────
        if self.DATABASE_URL.startswith("postgres://"):
            object.__setattr__(
                self, "DATABASE_URL",
                "postgresql://" + self.DATABASE_URL[len("postgres://"):]
            )

        # ── Warn (don't crash) if SECRET_KEY is still the default ─────────────
        if self.ENVIRONMENT == "production" and self.SECRET_KEY == DEFAULT_SECRET:
            warnings.warn(
                "CRITICAL: SECRET_KEY is still the default value! "
                "Set a strong random SECRET_KEY in Railway environment variables.",
                stacklevel=2,
            )


settings = Settings()
