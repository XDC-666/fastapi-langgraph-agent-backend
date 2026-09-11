"""健康检查路由：探测数据库与 Redis 是否可用。"""
from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.utils.cache import ping

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/health", tags=["health"])


def check_database() -> bool:
    """同步数据库探针；由 async 路由在线程池调用。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


@router.get("")
async def health():
    """返回服务依赖健康状态，不在事件循环直接执行同步 DB I/O。"""
    db_ok = await run_in_threadpool(check_database)
    redis_ok = await ping()

    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "database": db_ok,
        "redis": redis_ok,
    }
