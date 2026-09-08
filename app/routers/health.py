"""健康检查路由：探测数据库与 Redis 是否可用。"""
from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.utils.cache import ping

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/health", tags=["health"])


@router.get("")
async def health():
    """返回服务依赖健康状态。"""
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False

    redis_ok = await ping()

    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "database": db_ok,
        "redis": redis_ok,
    }
