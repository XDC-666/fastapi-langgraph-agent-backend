"""Redis 缓存工具。

使用异步 redis 客户端。项目中用于：
- 对话上下文缓存
- 简易限流（如登录尝试）
"""
import redis.asyncio as aioredis

from app.config import settings

# 全局异步客户端
redis_client: aioredis.Redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def get_redis() -> aioredis.Redis:
    """FastAPI 依赖：返回 Redis 客户端。"""
    return redis_client


async def ping() -> bool:
    """探测 Redis 是否可用。"""
    try:
        return await redis_client.ping()
    except Exception:
        return False
