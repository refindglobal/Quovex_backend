from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict


# ─── Auth ──────────────────────────────────────────────────────────────────────

class AuthTokenIn(BaseModel):
    firebase_token: str
    referral_code: Optional[str] = None
    device_id: Optional[str] = None


class AuthFirebaseIn(BaseModel):
    firebase_uid: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    referral_code: Optional[str] = None


class AuthOut(BaseModel):
    user: "UserProfileOut"


# ─── User Profile ──────────────────────────────────────────────────────────────

class UserProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    firebase_uid: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    exam_tags: Optional[List[str]] = []
    primary_subject: Optional[str] = None
    points_total: int = 0
    verified_minutes_total: int = 0
    quiz_points_total: int = 0
    verified_quiz_score: int = 0
    streak_count: int = 0
    last_study_date: Optional[datetime] = None
    streak_frozen_until: Optional[datetime] = None
    xp_boost_until: Optional[datetime] = None
    social_unlock_minutes_today: int = 0
    social_unlock_reset_at: Optional[datetime] = None
    ad_doubles_used_today: int = 0
    ad_doubles_reset_at: Optional[datetime] = None
    device_id: Optional[str] = None
    is_banned: bool = False
    full_name: Optional[str] = None
    age: Optional[int] = None
    institution_type: Optional[str] = None
    institution_name: Optional[str] = None
    class_or_year: Optional[str] = None
    education_type: Optional[str] = None
    exam_target: Optional[str] = None
    study_goal: Optional[str] = None
    daily_target_hours: Optional[float] = None
    blocked_apps: Optional[List[str]] = []
    study_time_preference: Optional[str] = None
    reset_time_hour: Optional[int] = 8
    lock_mode: Optional[str] = "STRICT"
    wallet_minutes: Optional[int] = 120
    profile_complete: bool = False
    referral_code: Optional[str] = None
    referred_by_id: Optional[UUID] = None
    referral_bonus_earned: int = 0
    first_session_completed: bool = False
    fcm_token: Optional[str] = None
    last_active: Optional[datetime] = None
    app_lock_enabled: bool = False
    app_lock_credits: int = 0
    locked_app_packages: Optional[List[str]] = None
    daily_study_target_minutes: int = 120
    language: str = "en"
    notification_prefs: Optional[dict] = None
    admin_role: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserUpdateIn(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    exam_tags: Optional[list] = None
    primary_subject: Optional[str] = None
    full_name: Optional[str] = None
    age: Optional[int] = None
    institution_type: Optional[str] = None
    institution_name: Optional[str] = None
    class_or_year: Optional[str] = None
    education_type: Optional[str] = None
    exam_target: Optional[str] = None
    study_goal: Optional[str] = None
    daily_target_hours: Optional[float] = None
    blocked_apps: Optional[List[str]] = None
    study_time_preference: Optional[str] = None
    reset_time_hour: Optional[int] = None
    lock_mode: Optional[str] = None
    wallet_minutes: Optional[int] = None
    daily_study_target_minutes: Optional[int] = None
    language: Optional[str] = None
    notification_prefs: Optional[dict] = None
    profile_complete: Optional[bool] = None


class UserPublicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    verified_minutes_total: int = 0
    verified_quiz_score: int = 0
    quiz_points_total: int = 0
    points_total: int = 0
    streak_count: int = 0
    last_study_date: Optional[datetime] = None
    exam_tags: Optional[list] = None


# ─── Subject Breakdown ─────────────────────────────────────────────────────────

class MonthlyAccuracyOut(BaseModel):
    month: str
    accuracy: float


class TopicBreakdownOut(BaseModel):
    topic_id: UUID
    topic_name: str
    questions_answered: int
    correct: int
    accuracy: float
    study_minutes: int


class SubjectBreakdownOut(BaseModel):
    subject: str
    total_study_minutes: int
    total_quiz_questions: int
    total_quiz_correct: int
    avg_accuracy: float
    topics_count: int
    monthly_accuracy: list[MonthlyAccuracyOut] = []
    topics: list[TopicBreakdownOut] = []


# ─── Leaderboard ───────────────────────────────────────────────────────────────

class LeaderboardEntryOut(BaseModel):
    user_id: Optional[UUID] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    country: Optional[str] = None
    verified_minutes: int = 0
    verified_quiz_score: int = 0
    points: int = 0
    rank: Optional[int] = None


class LeaderboardOut(BaseModel):
    track: str
    scope: str
    period: str
    entries: list[LeaderboardEntryOut]
    user_rank: Optional[LeaderboardEntryOut] = None
    total: int


# ─── Badges ────────────────────────────────────────────────────────────────────

class BadgeOut(BaseModel):
    badge_code: str
    earned_at: datetime


# ─── App Lock ──────────────────────────────────────────────────────────────────

class AppLockStatusOut(BaseModel):
    enabled: bool
    credits: int
    locked_apps: list


class AppLockUpdateIn(BaseModel):
    enabled: Optional[bool] = None
    locked_app_packages: Optional[list] = None


class AppLockConsumeIn(BaseModel):
    credits_used: int


class AppLockConsumeOut(BaseModel):
    remaining_credits: int
    message: str


class AppLockAdUnlockOut(BaseModel):
    credits_added: int
    total_credits: int
    success: bool
    message: str


class AppLockCreditsOut(BaseModel):
    credits: int
    max_credits: int
    message: str


class DailyTargetUpdateIn(BaseModel):
    daily_study_target_minutes: int


# ─── Sessions ──────────────────────────────────────────────────────────────────

class SessionStartIn(BaseModel):
    mode: str
    subject_tag: Optional[str] = None
    exam_tag: Optional[str] = None
    topic_id: Optional[UUID] = None
    locked_apps: Optional[list] = None
    whitelist_apps: Optional[list] = None


class SessionStartOut(BaseModel):
    session_id: UUID
    started_at: datetime
    mode: str


class SessionEndIn(BaseModel):
    session_id: UUID
    honor_check_failures: Optional[int] = None


class SessionEndOut(BaseModel):
    session_id: UUID
    verified_minutes: int
    points_awarded: int
    points_base: int
    streak_count: int
    ad_double_available: bool
    social_unlock_minutes_earned: int
    wallet_minutes_earned: int = 0   # 15 min per verified study hour (PRD §4.2)
    flagged: bool
    message: str
    new_badges: Optional[list] = None
    daily_target_met: bool = False


class SessionAdDoubleIn(BaseModel):
    session_id: UUID


class SessionAdDoubleOut(BaseModel):
    points_awarded: int
    success: bool
    message: str


class SessionPauseOut(BaseModel):
    status: str
    paused_at: datetime


class SessionResumeOut(BaseModel):
    status: str
    resumed_at: datetime


class SessionHeartbeatIn(BaseModel):
    liveness_passed: Optional[bool] = None
    app_violation_count: Optional[int] = None


class SessionHeartbeatOut(BaseModel):
    status: str
    elapsed_seconds: int


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    mode: str
    start_time: datetime
    end_time: Optional[datetime] = None
    verified_minutes: int = 0
    raw_minutes: int = 0
    points_awarded: int = 0
    points_base: int = 0
    ad_doubled: bool = False
    subject_tag: Optional[str] = None
    exam_tag: Optional[str] = None
    topic_id: Optional[UUID] = None
    locked_app_count: int = 0
    whitelist_apps: Optional[list] = None
    honor_check_failures: int = 0
    flagged: bool = False
    flag_reason: Optional[str] = None
    anti_cheat_score: float = 0.0
    is_active: bool = True
    is_paused: bool = False
    paused_at: Optional[datetime] = None
    total_paused_seconds: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SocialUnlockOut(BaseModel):
    minutes_remaining: int
    minutes_earned_today: int
    ad_bonus_available: bool
    ad_bonus_cooldown_seconds: Optional[int] = None


class SocialUnlockAdOut(BaseModel):
    minutes_added: int
    minutes_remaining: int
    next_ad_available_at: datetime
    success: bool


# ─── Quiz ──────────────────────────────────────────────────────────────────────

class QuizStartIn(BaseModel):
    subject: str
    exam_tag: Optional[str] = None
    grade_or_tag: Optional[str] = None
    topic_id: Optional[UUID] = None
    difficulty: Optional[str] = "adaptive"
    question_count: Optional[int] = None


class QuizQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    options: Optional[list] = None
    question_type: str
    subject: str
    exam_tag: Optional[str] = None
    grade_or_tag: Optional[str] = None
    difficulty: str


class QuizStartOut(BaseModel):
    quiz_session_id: UUID
    questions: list[QuizQuestionOut]
    grade_or_tag: Optional[str] = None
    started_at: datetime


class QuizAnswerIn(BaseModel):
    quiz_session_id: UUID
    question_id: UUID
    selected_answer: str
    response_time_ms: Optional[int] = None


class QuizAnswerOut(BaseModel):
    is_correct: bool
    correct_answer: str
    explanation: Optional[str] = None
    points_awarded: int


class QuizCompleteOut(BaseModel):
    quiz_session_id: UUID
    total_correct: int
    total_questions: int
    accuracy_percent: float
    points_earned: int
    verified_quiz_score_earned: int
    grade_or_tag: Optional[str] = None
    ad_double_available: bool
    bonus_questions_available: bool
    message: str


class QuizAdDoubleIn(BaseModel):
    quiz_session_id: UUID


class QuizAdDoubleOut(BaseModel):
    points_earned: int
    success: bool
    message: str


class SubjectProgressOut(BaseModel):
    subject: str
    accuracy: float = 0.0
    questions_answered: int = 0


class TopicQuizIn(BaseModel):
    topic: str
    subject: Optional[str] = None
    exam_tag: Optional[str] = None
    question_count: int = 5
    difficulty: Optional[str] = "adaptive"


class TopicQuizOut(BaseModel):
    quiz_id: str
    questions: list[QuizQuestionOut]
    topic: str
    generated_at: str


class DailyQuizOut(BaseModel):
    quiz_id: str
    questions: list[QuizQuestionOut]
    date: str
    expires_at: str


# ─── Topics ────────────────────────────────────────────────────────────────────

class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    subject: str
    exam_tag: Optional[str] = None
    display_order: int = 0


class TopicProgressOut(BaseModel):
    topic_id: UUID
    topic_name: str
    subject: str
    questions_answered: int
    correct: int
    accuracy: float
    study_minutes: int


# ─── Reports ───────────────────────────────────────────────────────────────────

class UserReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    report_type: str
    period_start: datetime
    period_end: datetime
    summary: str
    highlights: Optional[list] = None
    recommendations: Optional[list] = None
    generated_at: datetime
    read_at: Optional[datetime] = None


class ReportGenerateIn(BaseModel):
    report_type: str


class ReportGenerateOut(BaseModel):
    report_id: UUID
    message: str


# ─── Referral ──────────────────────────────────────────────────────────────────

class ReferralStatsOut(BaseModel):
    referral_code: str
    total_referred: int
    bonus_points_earned: int
    pending_referrals: int


class ReferralClaimIn(BaseModel):
    referred_user_id: UUID


class ReferralClaimOut(BaseModel):
    points_awarded: int
    total_bonus: int
    message: str


class ReferralGenerateOut(BaseModel):
    referral_code: str


# ─── Admin ─────────────────────────────────────────────────────────────────────

class AdminUserListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None
    points_total: int = 0
    verified_minutes_total: int = 0
    streak_count: int = 0
    is_banned: bool = False
    admin_role: Optional[str] = None
    created_at: Optional[datetime] = None
    last_active: Optional[datetime] = None


class AdminUserDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    firebase_uid: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    exam_tags: Optional[list] = None
    primary_subject: Optional[str] = None
    points_total: int = 0
    verified_minutes_total: int = 0
    quiz_points_total: int = 0
    verified_quiz_score: int = 0
    streak_count: int = 0
    is_banned: bool = False
    ban_reason: Optional[str] = None
    admin_role: Optional[str] = None
    full_name: Optional[str] = None
    age: Optional[int] = None
    institution_type: Optional[str] = None
    institution_name: Optional[str] = None
    class_or_year: Optional[str] = None
    profile_complete: bool = False
    referral_code: Optional[str] = None
    referral_bonus_earned: int = 0
    first_session_completed: bool = False
    daily_study_target_minutes: int = 120
    app_lock_enabled: bool = False
    app_lock_credits: int = 0
    locked_app_packages: Optional[list] = None
    language: str = "en"
    sessions: Optional[list] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AdminUserUpdateIn(BaseModel):
    is_banned: Optional[bool] = None
    ban_reason: Optional[str] = None
    admin_role: Optional[str] = None
    points_adjustment: Optional[int] = None
    adjustment_reason: Optional[str] = None
    daily_study_target_minutes: Optional[int] = None


class AdminSessionFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    user_name: Optional[str] = None
    mode: str
    start_time: datetime
    end_time: Optional[datetime] = None
    verified_minutes: int = 0
    raw_minutes: int = 0
    anti_cheat_score: float = 0.0
    flag_reason: Optional[str] = None
    flagged: bool = False
    subject_tag: Optional[str] = None
    exam_tag: Optional[str] = None
    honor_check_failures: int = 0
    is_paused: bool = False
    total_paused_seconds: int = 0


class AdminSessionActionIn(BaseModel):
    action: str
    notes: Optional[str] = None


class AdminOverviewOut(BaseModel):
    dau: int
    mau: int
    sessions_today: int
    verified_minutes_today: int
    total_users: int
    active_sessions: int
    active_groups: int
    avg_focus_time_minutes: float
    quizzes_completed: int
    anti_cheat_flags: int
    premium_subscribers: int


class QuizQuestionAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    options: Optional[list] = None
    correct_answer: str
    explanation: Optional[str] = None
    question_type: str
    subject: str
    exam_tag: Optional[str] = None
    grade_or_tag: Optional[str] = None
    difficulty: str
    status: str
    numerical_tolerance: Optional[float] = None
    reviewed_by: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    generated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class QuizQuestionUpdateIn(BaseModel):
    text: Optional[str] = None
    options: Optional[list] = None
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    subject: Optional[str] = None
    exam_tag: Optional[str] = None
    difficulty: Optional[str] = None
    status: Optional[str] = None
    numerical_tolerance: Optional[float] = None


class RewardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    track: str
    period_month: str
    tier: str
    rank_at_freeze: int
    reward_type: str
    reward_amount_usd: Optional[float] = None
    reward_description: Optional[str] = None
    status: str
    kyc_verified: bool = False
    claimed_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class PaginatedOut(BaseModel):
    items: list
    total: int
    offset: int
    limit: int


class NotificationComposePush(BaseModel):
    title: str
    body: str
    trigger_reason: Optional[str] = None
    segment_filter: Optional[dict] = None
    segment_country: Optional[str] = None
    segment_exam_tag: Optional[str] = None
    segment_streak_min: Optional[int] = None
    segment_inactive_days: Optional[int] = None


# ─── App Version (Phase 7) ─────────────────────────────────────────────────────

class AppVersionCheckOut(BaseModel):
    latest_version: str
    min_version: str
    update_url: str
    force_update: bool
    release_notes: Optional[str] = None


# ─── Admin: Badges ─────────────────────────────────────────────────────────────

class AdminBadgeOut(BaseModel):
    id: UUID
    user_id: UUID
    user_name: Optional[str] = None
    badge_code: str
    earned_at: datetime


class AdminBadgeAwardIn(BaseModel):
    user_id: UUID
    badge_code: str


class AdminBadgeStatsOut(BaseModel):
    badge_code: str
    awarded_count: int


# ─── Admin: App Lock ───────────────────────────────────────────────────────────

class AdminAppLockUserOut(BaseModel):
    user_id: UUID
    display_name: Optional[str] = None
    email: Optional[str] = None
    app_lock_enabled: bool
    app_lock_credits: int
    locked_packages_count: int = 0


class AdminAppLockForceUnlockOut(BaseModel):
    user_id: UUID
    app_lock_enabled: bool
    message: str


# ─── Admin: Topics ─────────────────────────────────────────────────────────────

class AdminTopicCreateIn(BaseModel):
    name: str
    subject: str
    exam_tag: Optional[str] = None
    display_order: int = 0


class AdminTopicUpdateIn(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    exam_tag: Optional[str] = None
    display_order: Optional[int] = None


class AdminTopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    subject: str
    exam_tag: Optional[str] = None
    display_order: int = 0
    student_count: int = 0


# ─── Admin: Referral ───────────────────────────────────────────────────────────

class AdminReferralStatsOut(BaseModel):
    total_referred_users: int
    total_bonus_paid: int
    top_referrers: list[dict] = []


class AdminReferralUserOut(BaseModel):
    user_id: UUID
    display_name: Optional[str] = None
    email: Optional[str] = None
    referral_code: Optional[str] = None
    referred_by_name: Optional[str] = None
    referred_users_count: int = 0
    referral_bonus_earned: int = 0


# ─── Admin: Reports ────────────────────────────────────────────────────────────

class AdminReportOut(BaseModel):
    id: UUID
    user_id: UUID
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    report_type: str
    period_start: datetime
    period_end: datetime
    summary: str
    generated_at: datetime
    read_at: Optional[datetime] = None


# ─── Grade Subjects (class-wise subject selection) ─────────────────────────────

class GradeSubjectCreateIn(BaseModel):
    grade_or_tag: str
    subject_name: str
    display_order: int = 0


class GradeSubjectUpdateIn(BaseModel):
    subject_name: Optional[str] = None
    display_order: Optional[int] = None


class GradeSubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    grade_or_tag: str
    subject_name: str
    display_order: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ─── AI Doubt Solver ──────────────────────────────────────────────────────────

class ChatMessageIn(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class DoubtSolveIn(BaseModel):
    question_text: str
    subject: Optional[str] = "General"
    image_base64: Optional[str] = None   # base64 of photo from OCR camera
    follow_up_action: Optional[str] = None  # "simplify" | "example" | "derive" | "quiz_me"
    chat_history: Optional[list[ChatMessageIn]] = None
    user_context: Optional[str] = None


class DoubtStepOut(BaseModel):
    step: int
    title: str
    content: str


class DoubtSolveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    doubt_id: UUID
    question_text: str
    subject: str
    question_type: str = "factual"        # factual | numerical | conceptual | teach_me
    confidence: str = "high"              # high | medium | estimated
    confidence_label: str = "Textbook verified"
    steps: list[DoubtStepOut]
    final_answer: str
    key_concepts: list[str]
    related_topics: list[str]


class DoubtHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    doubt_id: UUID
    question_text: str
    subject: str
    final_answer: str
    key_concepts: list[str]
    is_bookmarked: bool
    created_at: Optional[datetime] = None


class DoubtBookmarkIn(BaseModel):
    doubt_id: UUID
    is_bookmarked: bool


# ─── OCR Camera ───────────────────────────────────────────────────────────────

class OcrExtractIn(BaseModel):
    image_base64: str   # base64-encoded image


class OcrExtractOut(BaseModel):
    extracted_text: str
    detected_subject: Optional[str] = None
    confidence: float = 0.0
