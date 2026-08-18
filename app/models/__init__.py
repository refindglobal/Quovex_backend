import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime,
    ForeignKey, Text, Enum as SAEnum, ARRAY, BigInteger, JSON, Uuid
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.db.session import Base


# ─── Enums ──────────────────────────────────────────────────────────────────

class StudyMode(str, enum.Enum):
    offline = "offline"
    online = "online"
    focus = "focus"
    exam = "exam"
    custom = "custom"
    pomodoro = "pomodoro"


class QuestionType(str, enum.Enum):
    mcq = "mcq"
    true_false = "true_false"
    numerical = "numerical"
    assertion_reason = "assertion_reason"


class QuestionStatus(str, enum.Enum):
    pending_review = "pending_review"
    live = "live"
    rejected = "rejected"


class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"
    adaptive = "adaptive"


class LeaderboardTrack(str, enum.Enum):
    study = "study"
    quiz = "quiz"
    overall = "overall"


class LeaderboardScope(str, enum.Enum):
    friends = "friends"
    state = "state"
    country = "country"
    global_ = "global"


class LeaderboardPeriod(str, enum.Enum):
    week = "week"
    month = "month"
    all_time = "all_time"


class RewardStatus(str, enum.Enum):
    pending = "pending"
    kyc_review = "kyc_review"
    approved = "approved"
    sent = "sent"
    rejected = "rejected"


class RewardType(str, enum.Enum):
    giftcard = "giftcard"
    badge = "badge"
    physical_item = "physical_item"


class AdminRole(str, enum.Enum):
    superadmin = "superadmin"
    support = "support"


class InstitutionType(str, enum.Enum):
    school = "school"
    college = "college"
    coaching = "coaching"
    self_study = "self_study"


class NotificationType(str, enum.Enum):
    event = "event"
    scheduled = "scheduled"


# ─── Mixins ─────────────────────────────────────────────────────────────────

class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ─── Models ─────────────────────────────────────────────────────────────────

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid = Column(String(128), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    display_name = Column(String(100), nullable=True)
    avatar_url = Column(Text, nullable=True)

    # Location
    country = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)

    # Exam tagging
    exam_tags = Column(JSON, nullable=True, default=[])
    primary_subject = Column(String(100), nullable=True)

    # Stats (cumulative)
    points_total = Column(BigInteger, default=0, nullable=False)
    verified_minutes_total = Column(BigInteger, default=0, nullable=False)
    quiz_points_total = Column(BigInteger, default=0, nullable=False)
    verified_quiz_score = Column(BigInteger, default=0, nullable=False)

    # Streak
    streak_count = Column(Integer, default=0, nullable=False)
    last_study_date = Column(DateTime(timezone=True), nullable=True)
    streak_frozen_until = Column(DateTime(timezone=True), nullable=True)
    xp_boost_until = Column(DateTime(timezone=True), nullable=True)

    # Social unlock bank (minutes remaining today)
    social_unlock_minutes_today = Column(Integer, default=0, nullable=False)
    social_unlock_reset_at = Column(DateTime(timezone=True), nullable=True)

    # Ad doubling usage (resets daily)
    ad_doubles_used_today = Column(Integer, default=0, nullable=False)
    ad_doubles_reset_at = Column(DateTime(timezone=True), nullable=True)

    # Anti-cheat
    device_id = Column(String(255), nullable=True, index=True)
    is_banned = Column(Boolean, default=False, nullable=False)
    ban_reason = Column(Text, nullable=True)

    # Admin
    admin_role = Column(SAEnum(AdminRole), nullable=True)
    password_hash = Column(Text, nullable=True)  # Only set for admin dashboard users (bcrypt)

    # ── Academic Profile (collected at signup, used for reports & question gen) ──
    full_name = Column(String(150), nullable=True)  # Legal / preferred full name
    age = Column(Integer, nullable=True)             # Student age (2-50)
    institution_type = Column(
        SAEnum(InstitutionType), nullable=True,
        comment="school | college | coaching | self_study"
    )
    institution_name = Column(String(200), nullable=True)  # School / college name
    class_or_year = Column(String(50), nullable=True)
    # e.g. "Class 10", "Class 12", "1st Year", "2nd Year", "Dropper"
    class_auto_advanced_year = Column(
        Integer, nullable=True,
        comment="The year in which class_or_year was last auto-advanced (April 1 job)"
    )
    education_type = Column(String(100), nullable=True)
    exam_target = Column(String(100), nullable=True)
    study_goal = Column(String(150), nullable=True)
    daily_target_hours = Column(Float, default=4.0, nullable=True)
    blocked_apps = Column(JSON, nullable=True, default=[])
    study_time_preference = Column(String(100), nullable=True)

    # Quovex Freedom Lock fields
    reset_time_hour = Column(Integer, default=8, nullable=True, comment="Daily reset time (default 8 for 8:00 AM)")
    lock_mode = Column(String(50), default="STRICT", nullable=True, comment="STRICT | SMART | WEEKEND_RELAXED")
    wallet_minutes = Column(Integer, default=0, nullable=True, comment="Study Wallet balance in minutes")
    welcome_gift_claimed = Column(Boolean, default=False, nullable=True, comment="True once user claims onboarding welcome gift")

    profile_complete = Column(Boolean, default=False, nullable=False,
                              comment="True once user finishes the post-signup profile form")
    referral_code = Column(String(20), unique=True, nullable=True, index=True)
    referred_by_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    referral_bonus_earned = Column(Integer, default=0, nullable=False)
    referral_bonus_paid = Column(Boolean, default=False, nullable=False)
    first_session_completed = Column(Boolean, default=False, nullable=False)

    # FCM push token
    fcm_token = Column(Text, nullable=True)

    # Last activity timestamp
    last_active = Column(DateTime(timezone=True), nullable=True)

    # App lock
    app_lock_enabled = Column(Boolean, default=False, nullable=False)
    app_lock_credits = Column(Integer, default=0, nullable=False)
    locked_app_packages = Column(JSON, nullable=True, default=[])
    last_ad_unlock_at = Column(DateTime(timezone=True), nullable=True)
    ad_unlock_count_today = Column(Integer, default=0, nullable=False)
    ad_unlock_reset_at = Column(DateTime(timezone=True), nullable=True)

    # Daily study target (auto-unlock)
    daily_study_target_minutes = Column(Integer, default=120, nullable=False)

    # Language preference
    language = Column(String(10), default="en", nullable=False)

    # Last known leaderboard ranks per track (JSON)
    last_known_ranks = Column(JSON, default=None, nullable=True)

    # Notification preferences (JSON)
    notification_prefs = Column(JSON, default={
        "daily_recap": True,
        "streak_reminder": True,
        "rank_change": True,
        "badge_unlock": True,
        "weak_subject_nudge": True,
        "reward_announcement": True,
    })

    # Relationships
    sessions = relationship("Session", back_populates="user", lazy="select")
    quiz_sessions = relationship("QuizSession", back_populates="user", lazy="select")
    subject_proficiencies = relationship("UserSubjectProficiency", back_populates="user", lazy="select")
    leaderboard_snapshots = relationship("LeaderboardSnapshot", back_populates="user", lazy="select")
    rewards = relationship("Reward", back_populates="user", lazy="select")
    notification_logs = relationship("NotificationLog", back_populates="user", lazy="select")
    badges = relationship("Badge", back_populates="user", lazy="select")
    topic_progress = relationship("UserTopicProgress", back_populates="user", lazy="select")
    reports = relationship("UserReport", back_populates="user", lazy="select")
    app_usage_logs = relationship("AppUsageLog", back_populates="user", lazy="select")
    referred_by = relationship("User", remote_side="User.id", back_populates="referred_users")
    referred_users = relationship("User", back_populates="referred_by", lazy="select")


class UserSubjectProficiency(Base, TimestampMixin):
    """Tracks per-user, per-subject quiz accuracy for adaptive difficulty."""
    __tablename__ = "user_subject_proficiencies"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subject = Column(String(100), nullable=False)
    exam_tag = Column(String(100), nullable=True)

    # Rolling accuracy score (0.0 to 1.0, simple EMA)
    rolling_accuracy_score = Column(Float, default=0.5, nullable=False)
    total_questions_answered = Column(Integer, default=0, nullable=False)
    total_correct = Column(Integer, default=0, nullable=False)

    # For trend tracking (monthly snapshots stored as JSONB)
    monthly_accuracy_history = Column(JSON, default=[], nullable=False)

    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="subject_proficiencies")


class Session(Base, TimestampMixin):
    """A study session."""
    __tablename__ = "sessions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    mode = Column(SAEnum(StudyMode), nullable=False, default=StudyMode.offline)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)

    # Results
    verified_minutes = Column(Integer, default=0, nullable=False)
    raw_minutes = Column(Integer, default=0, nullable=False)
    points_awarded = Column(Integer, default=0, nullable=False)
    points_base = Column(Integer, default=0, nullable=False)  # before ad doubling

    # Ad mechanics
    ad_doubled = Column(Boolean, default=False, nullable=False)
    ad_double_count = Column(Integer, default=0, nullable=False)

    # Subject tagging
    subject_tag = Column(String(100), nullable=True)
    exam_tag = Column(String(100), nullable=True)
    topic_id = Column(Uuid(as_uuid=True), ForeignKey("topics.id"), nullable=True)

    # Lock list (offline mode)
    locked_app_count = Column(Integer, default=0, nullable=False)

    # Online mode
    whitelist_apps = Column(JSON, nullable=True, default=[])
    honor_check_failures = Column(Integer, default=0, nullable=False)

    # Anti-cheat
    flagged = Column(Boolean, default=False, nullable=False)
    flag_reason = Column(Text, nullable=True)
    anti_cheat_score = Column(Float, default=0.0, nullable=False)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_paused = Column(Boolean, default=False, nullable=False)
    paused_at = Column(DateTime(timezone=True), nullable=True)
    total_paused_seconds = Column(Integer, default=0, nullable=False)

    user = relationship("User", back_populates="sessions")


class QuizQuestion(Base, TimestampMixin):
    """AI-generated quiz question. Goes through pending_review → live or rejected."""
    __tablename__ = "quiz_questions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    text = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)  # List of option strings for MCQ/AR
    correct_answer = Column(String(500), nullable=False)
    explanation = Column(Text, nullable=True)

    question_type = Column(SAEnum(QuestionType), nullable=False, default=QuestionType.mcq)
    subject = Column(String(500), nullable=False, index=True)
    exam_tag = Column(String(255), nullable=True, index=True)
    grade_or_tag = Column(String(255), nullable=True, index=True)
    difficulty = Column(SAEnum(Difficulty), nullable=False, default=Difficulty.medium, index=True)
    status = Column(SAEnum(QuestionStatus), nullable=False, default=QuestionStatus.pending_review, index=True)

    # For numerical type: acceptable tolerance
    numerical_tolerance = Column(Float, nullable=True)

    # Admin review
    reviewed_by = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Generation metadata
    generation_batch_id = Column(String(100), nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    answers = relationship("QuizAnswer", back_populates="question", lazy="select")


class QuizSession(Base, TimestampMixin):
    """A single quiz attempt by a user."""
    __tablename__ = "quiz_sessions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    subject = Column(String(500), nullable=True)
    exam_tag = Column(String(255), nullable=True)
    grade_or_tag = Column(String(255), nullable=True)
    topic_id = Column(Uuid(as_uuid=True), ForeignKey("topics.id"), nullable=True)
    difficulty_mode = Column(SAEnum(Difficulty), nullable=False, default=Difficulty.adaptive)

    question_ids = Column(JSON, nullable=False, default=[])
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)

    # Scoring
    total_correct = Column(Integer, default=0, nullable=False)
    total_questions = Column(Integer, default=0, nullable=False)
    points_earned = Column(Integer, default=0, nullable=False)
    verified_quiz_score_earned = Column(Integer, default=0, nullable=False)

    # Ad mechanics
    ad_doubled = Column(Boolean, default=False, nullable=False)
    bonus_questions_added = Column(Boolean, default=False, nullable=False)

    is_complete = Column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="quiz_sessions")
    answers = relationship("QuizAnswer", back_populates="quiz_session", lazy="select")


class QuizAnswer(Base):
    """Individual answer in a quiz session."""
    __tablename__ = "quiz_answers"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_session_id = Column(Uuid(as_uuid=True), ForeignKey("quiz_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Uuid(as_uuid=True), ForeignKey("quiz_questions.id"), nullable=False, index=True)

    selected_answer = Column(String(500), nullable=True)
    is_correct = Column(Boolean, nullable=False, default=False)
    response_time_ms = Column(Integer, nullable=True)  # milliseconds

    points_awarded = Column(Integer, default=0, nullable=False)
    # True = bonus question (counts toward verified_quiz_score), False = ad-doubled (doesn't count)
    counts_toward_verified_score = Column(Boolean, default=True, nullable=False)

    answered_at = Column(DateTime(timezone=True), server_default=func.now())

    quiz_session = relationship("QuizSession", back_populates="answers")
    question = relationship("QuizQuestion", back_populates="answers")


class LeaderboardSnapshot(Base):
    """Periodic snapshot of leaderboard rankings."""
    __tablename__ = "leaderboard_snapshots"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    track = Column(SAEnum(LeaderboardTrack), nullable=False, index=True)
    scope = Column(SAEnum(LeaderboardScope), nullable=False, index=True)
    period = Column(SAEnum(LeaderboardPeriod), nullable=False, index=True)

    rank = Column(Integer, nullable=False)
    verified_minutes = Column(BigInteger, default=0, nullable=False)
    verified_quiz_score = Column(BigInteger, default=0, nullable=False)
    points = Column(BigInteger, default=0, nullable=False)

    # For filtering
    country = Column(String(100), nullable=True)
    state_region = Column(String(100), nullable=True)
    exam_tag = Column(String(100), nullable=True)

    snapshot_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    is_frozen = Column(Boolean, default=False, nullable=False)  # True = month-end freeze for rewards

    user = relationship("User", back_populates="leaderboard_snapshots")


class Reward(Base, TimestampMixin):
    """Monthly reward for a top performer."""
    __tablename__ = "rewards"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    track = Column(SAEnum(LeaderboardTrack), nullable=False)
    period_month = Column(String(7), nullable=False)  # "2024-01"
    tier = Column(String(50), nullable=False)  # "top_3", "top_100", "top_1000"
    rank_at_freeze = Column(Integer, nullable=False)

    reward_type = Column(SAEnum(RewardType), nullable=False)
    reward_amount_usd = Column(Float, nullable=True)  # For gift cards
    reward_description = Column(String(255), nullable=True)
    custom_reward_name = Column(String(200), nullable=True)
    reward_image_url = Column(Text, nullable=True)

    status = Column(SAEnum(RewardStatus), nullable=False, default=RewardStatus.pending, index=True)
    kyc_verified = Column(Boolean, default=False, nullable=False)
    kyc_verification_id = Column(String(255), nullable=True)

    # KYC submission data (manual, student ID only)
    kyc_full_name = Column(String(150), nullable=True)
    kyc_phone = Column(String(20), nullable=True)  # WhatsApp number
    kyc_email = Column(String(255), nullable=True)
    kyc_student_id_type = Column(String(50), nullable=True)  # "School ID" / "College ID" / "Library Card"
    kyc_student_id_number = Column(String(100), nullable=True)
    kyc_institution_name = Column(String(200), nullable=True)
    kyc_student_id_image_url = Column(Text, nullable=True)  # Uploaded photo path
    kyc_notes = Column(Text, nullable=True)

    # Delivery address (for physical_item rewards)
    delivery_address_line1 = Column(String(255), nullable=True)
    delivery_address_line2 = Column(String(255), nullable=True)
    delivery_city = Column(String(100), nullable=True)
    delivery_state = Column(String(100), nullable=True)
    delivery_pincode = Column(String(20), nullable=True)
    delivery_landmark = Column(String(255), nullable=True)

    claimed_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    admin_notes = Column(Text, nullable=True)

    user = relationship("User", back_populates="rewards")


class RewardConfig(Base, TimestampMixin):
    """Per-month/track/tier reward configuration set by admin."""
    __tablename__ = "reward_configs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_month = Column(String(7), nullable=False, index=True)
    track = Column(SAEnum(LeaderboardTrack), nullable=False)
    position_label = Column(String(20), nullable=False,
                            comment="rank_1 | rank_2 | rank_3 | top_100 | top_1000")
    reward_name = Column(String(200), nullable=False)
    reward_type = Column(String(50), nullable=False,
                         comment="giftcard | badge | physical_item")
    amount_usd = Column(Float, nullable=True)
    image_url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class GradeSubject(Base, TimestampMixin):
    """Subject mapped to a grade/class/year or exam tag (e.g. Class 6 → Mathematics)."""
    __tablename__ = "grade_subjects"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grade_or_tag = Column(String(100), nullable=False, index=True)
    subject_name = Column(String(100), nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


class AdminActionLog(Base):
    """Audit log for all admin actions."""
    __tablename__ = "admin_action_logs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    action_type = Column(String(100), nullable=False)
    target_user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    target_resource_type = Column(String(50), nullable=True)
    target_resource_id = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    action_metadata = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class AdRevenueLog(Base):
    """Daily ad revenue tracking per placement type."""
    __tablename__ = "ad_revenue_logs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(DateTime(timezone=True), nullable=False, index=True)
    placement_type = Column(String(100), nullable=False)  # "post_session_double", "plus5min", etc.
    country = Column(String(100), nullable=True)
    impressions = Column(Integer, default=0, nullable=False)
    estimated_revenue_usd = Column(Float, default=0.0, nullable=False)
    ecpm = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class NotificationLog(Base):
    """Tracks notifications sent to users (for daily cap enforcement)."""
    __tablename__ = "notification_logs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    notification_type = Column(SAEnum(NotificationType), nullable=False)
    trigger_reason = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)

    sent_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    fcm_message_id = Column(String(255), nullable=True)
    success = Column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="notification_logs")


class OTPLog(Base):
    """Log of all OTP send/verify events for audit."""
    __tablename__ = "otp_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), nullable=False, index=True)
    otp_hash = Column(String(128), nullable=False)
    verified = Column(Boolean, default=False, nullable=False)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)


class AdminSetting(Base):
    """Key-value store for admin-configurable settings (DB-backed)."""
    __tablename__ = "admin_settings"

    key = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Badge(Base):
    """An achievement badge earned by a user."""
    __tablename__ = "badges"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    badge_code = Column(String(50), nullable=False, index=True)  # e.g. "milestone_100", "streak_7", "podium_study_1st"
    earned_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="badges")


class UserReport(Base):
    """AI-generated study report (daily or weekly)."""
    __tablename__ = "user_reports"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    report_type = Column(String(10), nullable=False, index=True)  # "daily" or "weekly"
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    summary = Column(Text, nullable=False)
    highlights = Column(JSON, nullable=True)
    recommendations = Column(JSON, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    read_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="reports")


class AppUsageLog(Base):
    """Tracks daily app open count per user."""
    __tablename__ = "app_usage_logs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(DateTime(timezone=True), nullable=False, index=True)
    open_count = Column(Integer, default=0, nullable=False)

    user = relationship("User", back_populates="app_usage_logs")


class Topic(Base):
    """A topic within a subject (e.g. Calculus under Mathematics)."""
    __tablename__ = "topics"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(500), nullable=False)
    subject = Column(String(500), nullable=False, index=True)
    exam_tag = Column(String(255), nullable=True)
    display_order = Column(Integer, default=0, nullable=False)

    user_progress = relationship("UserTopicProgress", back_populates="topic", lazy="select")


class UserTopicProgress(Base, TimestampMixin):
    """Per-user accuracy and study minutes per topic."""
    __tablename__ = "user_topic_progress"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = Column(Uuid(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True)
    questions_answered = Column(Integer, default=0, nullable=False)
    correct = Column(Integer, default=0, nullable=False)
    accuracy = Column(Float, default=0.0, nullable=False)
    study_minutes = Column(Integer, default=0, nullable=False)

    topic = relationship("Topic", back_populates="user_progress")
    user = relationship("User", back_populates="topic_progress")


class Doubt(Base, TimestampMixin):
    """AI Doubt Solver — stores question, step-by-step reasoning, and final answer."""
    __tablename__ = "doubts"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    subject = Column(String(500), nullable=False, default="General")
    image_url = Column(Text, nullable=True)
    # JSON: list of {"step": int, "title": str, "content": str}
    step_by_step_explanation = Column(JSON, default=list, nullable=False)
    final_answer = Column(Text, nullable=False, default="")
    # JSON: list of str (formulas / key rules)
    key_concepts = Column(JSON, default=list, nullable=False)
    # JSON: list of str (related topic names)
    related_topics = Column(JSON, default=list, nullable=False)
    is_bookmarked = Column(Boolean, default=False, nullable=False)

    user = relationship("User", backref="doubts")
