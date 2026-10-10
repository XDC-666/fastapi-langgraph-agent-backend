"""Redis 客户端与探活。"""
import redis.asyncio as aioredis

from app.config import settings

redis_client: aioredis.Redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def ping() -> bool:
    """探测 Redis 是否可用。"""
    try:
        return await redis_client.ping()
    except Exception:
        return False
