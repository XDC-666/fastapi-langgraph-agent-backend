"""基于 Redis 的登录失败锁定（防暴力破解）。

设计要点：
- 按登录标识（用户名/邮箱）计数失败次数，落在 `LOGIN_LOCKOUT_WINDOW_MINUTES` 窗口内。
- 达到 `LOGIN_MAX_FAILED_ATTEMPTS` 即在 Redis 写入带 TTL 的锁键，锁定 `LOGIN_LOCKOUT_MINUTES` 分钟。
- **降级放行**：Redis 不可用时跳过锁定逻辑，绝不因防护组件故障导致用户无法登录。
- 登录成功时清除该标识的失败计数与锁，避免「被锁定后改对密码仍被拦」。
"""
import logging

from app.config import settings
from app.utils.cache import redis_client

logger = logging.getLogger(__name__)


def _fail_key(identifier: str) -> str:
    return f"fail:login:{identifier}"


def _lock_key(identifier: str) -> str:
    return f"lock:login:{identifier}"


async def is_locked(identifier: str) -> int | None:
    """返回剩余锁定秒数；未锁定返回 None（Redis 异常同样返回 None = 放行）。"""
    try:
        ttl = await redis_client.ttl(_lock_key(identifier))
        return ttl if ttl and ttl > 0 else None
    except Exception:  # noqa: BLE001
        logger.warning("锁定组件不可用（Redis 异常），本次放行 identifier=%s", identifier)
        return None


async def record_failure(identifier: str, ip: str) -> None:
    """记录一次失败登录，必要时触发锁定。"""
    try:
        count = await redis_client.incr(_fail_key(identifier))
        if count == 1:
            # 仅首次计数设置窗口过期，避免窗口不断续期
            window = settings.LOGIN_LOCKOUT_WINDOW_MINUTES * 60
            await redis_client.expire(_fail_key(identifier), window)
        if count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            await redis_client.set(
                _lock_key(identifier), "1", ex=settings.LOGIN_LOCKOUT_MINUTES * 60
            )
            logger.warning(
                "账号 %s 因连续 %d 次登录失败被锁定 %d 分钟（ip=%s）",
                identifier,
                count,
                settings.LOGIN_LOCKOUT_MINUTES,
                ip,
            )
    except Exception:  # noqa: BLE001
        logger.warning("记录登录失败计数失败（Redis 异常），跳过 identifier=%s", identifier)


async def clear_lock(identifier: str) -> None:
    """登录成功后清除失败计数与锁。"""
    try:
        await redis_client.delete(_fail_key(identifier))
        await redis_client.delete(_lock_key(identifier))
    except Exception:  # noqa: BLE001
        logger.warning("清除登录锁定失败（Redis 异常），跳过 identifier=%s", identifier)
