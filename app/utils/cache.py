"""Redis 缓存工具。

使用异步 redis 客户端。项目中用于：
- 对话上下文缓存
- 简易限流（如登录尝试）
"""
import redis.asyncio as aioredis

from app.config import settings

# 全局异步客户端
#
# 必须显式设置连接 / 读写超时：Redis 只是辅助组件，不可用时上层会降级放行，
# 但「降级」不等于「可以无限等待」。不设超时时，一次 ping 会一直挂到系统级 TCP
# 连接超时，认证链路（is_locked → record_failure / clear_lock 共 2~3 次调用）
# 会被放大成数秒的响应延迟，健康检查同样被拖慢。
redis_client: aioredis.Redis = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SECONDS,
    socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
    retry_on_timeout=False,
    health_check_interval=30,
)


async def get_redis() -> aioredis.Redis:
    """FastAPI 依赖：返回 Redis 客户端。"""
    return redis_client


async def ping() -> bool:
    """探测 Redis 是否可用。"""
    try:
        return await redis_client.ping()
    except Exception:
        return False
