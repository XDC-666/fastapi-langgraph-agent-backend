"""Redis 客户端与探活。"""
import redis.asyncio as aioredis

from app.config import settings

redis_client: aioredis.Redis = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SECONDS,
    socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
    retry_on_timeout=False,
    health_check_interval=30,
)


async def ping() -> bool:
    """探测 Redis 是否可用。"""
    try:
        return await redis_client.ping()
    except Exception:
        return False
