"""用量统计路由。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.usage import UsageSummary
from app.services.usage_service import get_usage_summary

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/usage", tags=["usage"])


@router.get("/me", response_model=UsageSummary)
def my_usage(
    days: int = Query(30, ge=1, le=365, description="统计最近多少天"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回当前用户的 token 用量汇总（总计 / 按模型 / 按天 / 成本估算）。"""
    return get_usage_summary(db, current_user.id, days=days)
