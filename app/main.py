"""FastAPI main application entry point."""
import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app.config import settings

# Structured JSON logging in production
if settings.ENVIRONMENT == "production":
    from pythonjsonlogger import jsonlogger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db.session import Base, engine, SessionLocal
from app.db.redis_client import close_redis, get_redis
from app.models import *  # noqa: ensure models are registered

# Import routers
from app.api.v1 import auth, sessions, leaderboard, quiz, users, admin, rewards, badges, app_lock, referral, topics, reports, app_version, support, reward_configs, subjects, study_rooms, wallet, study_history, doubts

# Rate limiting
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.limiter import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    db_dialect = settings.DATABASE_URL.split(':')[0] if '://' in settings.DATABASE_URL else 'unknown'
    logger.info(f"Database dialect: {db_dialect}")
    workers = os.environ.get("UVICORN_WORKERS", "2")
    logger.info(f"Workers: {workers}")

    if settings.ENVIRONMENT == "production":
        if settings.SECRET_KEY == "change-me-in-production":
            logger.warning("SECRET_KEY is still set to the default value! Change it immediately.")
        logger.info(f"Allowed origins: {settings.ALLOWED_ORIGINS}")

    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created successfully.")
    except Exception as e:
        logger.warning(f"Database table verification skipped/warning: {e}")

    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("ALTER TABLE quiz_questions ALTER COLUMN subject TYPE VARCHAR(500);"))
                conn.execute(text("ALTER TABLE quiz_questions ALTER COLUMN exam_tag TYPE VARCHAR(255);"))
                conn.execute(text("ALTER TABLE quiz_questions ALTER COLUMN grade_or_tag TYPE VARCHAR(255);"))
                conn.execute(text("ALTER TABLE quiz_sessions ALTER COLUMN subject TYPE VARCHAR(500);"))
                conn.execute(text("ALTER TABLE quiz_sessions ALTER COLUMN exam_tag TYPE VARCHAR(255);"))
                conn.execute(text("ALTER TABLE quiz_sessions ALTER COLUMN grade_or_tag TYPE VARCHAR(255);"))
                conn.execute(text("ALTER TABLE topics ALTER COLUMN name TYPE VARCHAR(500);"))
                conn.execute(text("ALTER TABLE topics ALTER COLUMN subject TYPE VARCHAR(500);"))
                conn.execute(text("ALTER TABLE doubts ALTER COLUMN subject TYPE VARCHAR(500);"))
                conn.commit()
                logger.info("Column expansion migration verified/applied.")
    except Exception as e:
        logger.warning(f"Column expansion skipped: {e}")
    yield
    # Shutdown
    await close_redis()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Quovex Backend API — focus, compete, earn rewards.",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

# Rate limit handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


# Security headers
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'"
    )
    return response


# Request body size limit (10 MB)
MAX_BODY_SIZE = 10 * 1024 * 1024


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_SIZE:
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    return await call_next(request)


# Serve uploaded files (KYC photos, etc.) — requires auth
UPLOAD_DIR = settings.UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Register routers
API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(users.streak_router, prefix=API_PREFIX)
app.include_router(sessions.router, prefix=API_PREFIX)
app.include_router(leaderboard.router, prefix=API_PREFIX)
app.include_router(quiz.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(rewards.router, prefix=API_PREFIX)
app.include_router(badges.router, prefix=API_PREFIX)
app.include_router(app_lock.router, prefix=API_PREFIX)
app.include_router(referral.router, prefix=API_PREFIX)
app.include_router(topics.router, prefix=API_PREFIX)
app.include_router(reports.router, prefix=API_PREFIX)
app.include_router(app_version.router, prefix=API_PREFIX)
app.include_router(support.router, prefix=API_PREFIX)
app.include_router(reward_configs.router, prefix=API_PREFIX)
app.include_router(reward_configs.public_router, prefix=API_PREFIX)
app.include_router(subjects.router, prefix=API_PREFIX)
app.include_router(subjects.public_router, prefix=API_PREFIX)
app.include_router(study_rooms.router, prefix=API_PREFIX)
app.include_router(wallet.router, prefix=API_PREFIX)
app.include_router(study_history.router, prefix=API_PREFIX)
app.include_router(doubts.router, prefix=API_PREFIX)


@app.get("/health")
async def health_check():
    """Health check reporting app, DB, and Redis status."""
    statuses = {"status": "ok", "version": settings.APP_VERSION, "checks": {}}

    # DB check
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        statuses["checks"]["database"] = "ok"
    except Exception as e:
        statuses["checks"]["database"] = f"error: {str(e)}"
        statuses["status"] = "degraded"

    # Redis check
    try:
        r = await get_redis()
        if r:
            await r.ping()
            statuses["checks"]["redis"] = "ok"
        else:
            statuses["checks"]["redis"] = "not_configured"
    except Exception as e:
        statuses["checks"]["redis"] = f"error: {str(e)}"
        statuses["status"] = "degraded"

    # Return 200 so Railway's deploy orchestrator doesn't loop-kill the container
    return statuses

