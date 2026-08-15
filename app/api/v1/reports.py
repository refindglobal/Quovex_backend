"""Reports router - AI-generated study reports (daily/weekly)."""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import desc

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import User, UserReport
from app.schemas import UserReportOut, ReportGenerateIn, ReportGenerateOut
from app.services.report_service import generate_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/latest", response_model=UserReportOut)
async def get_latest_report(
    report_type: str = Query("daily", regex="^(daily|weekly)$"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the latest report of the given type for the current user."""
    report = (
        db.query(UserReport)
        .filter(
            UserReport.user_id == current_user.id,
            UserReport.report_type == report_type,
        )
        .order_by(desc(UserReport.generated_at))
        .first()
    )
    if not report:
        # On-demand generation when student requests report
        report = generate_report(current_user, report_type, db)
    return report


@router.post("/generate", response_model=ReportGenerateOut)
async def generate_new_report(
    body: ReportGenerateIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Generate a new AI-powered study report."""
    if body.report_type not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="report_type must be 'daily' or 'weekly'")
    report = generate_report(current_user, body.report_type, db)
    return ReportGenerateOut(
        report_id=report.id,
        message=f"{body.report_type.capitalize()} report generated successfully",
    )


@router.get("/history", response_model=list[UserReportOut])
async def get_report_history(
    report_type: str = Query(None, regex="^(daily|weekly)?$"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get report history for the current user."""
    query = db.query(UserReport).filter(UserReport.user_id == current_user.id)
    if report_type:
        query = query.filter(UserReport.report_type == report_type)
    reports = query.order_by(desc(UserReport.generated_at)).limit(limit).all()
    return reports
