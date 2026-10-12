"""基于 Redis 的固定窗口限流（INCR + EXPIRE）。

Redis 不可用时降级放行：限流是保护性措施，不应成为新的故障点。
"""
import logging

from fastapi import Depends, HTTPException, Request, status

from app.config import settings
from app.dependencies import get_current_user
from app.models.user import User
from app.utils.cache import redis_call, redis_client

logger = logging.getLogger(__name__)


async def is_allowed(key: str, limit: int, window_seconds: int) -> bool:
    """判断 key 在当前窗口内是否还有额度；Redis 异常时放行。

    整组操作（INCR + EXPIRE）作为一个整体丢给熔断层：失败只记账一次，
    不会因为一次语义操作里有两个命令就把失败计数翻倍。
    """

    async def _op() -> bool:
        count = await redis_client.incr(key)
        if count == 1:
            # 仅首次计数设置过期，保证是固定窗口而非不断续期
            await redis_client.expire(key, window_seconds)
        return count <= limit

    return await redis_call(f"rate_limit:{key}", _op, fallback=True)


def _client_ip(request: Request) -> str:
    """取客户端 IP。

    默认忽略 X-Forwarded-For（防伪造绕过限流）；仅在可信反代后
    （TRUST_PROXY=True）取 XFF 最左侧的原始客户端地址。
    """
    if settings.TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            client_ip = xff.split(",")[0].strip()
            if client_ip:
                return client_ip
    return request.client.host if request.client else "unknown"


async def login_rate_limit(request: Request) -> None:
    """登录限流：按 IP，防暴力破解。"""
    if not settings.RATE_LIMIT_ENABLED:
        return
    key = f"rl:login:{_client_ip(request)}"
    if not await is_allowed(key, settings.RATE_LIMIT_LOGIN_PER_MINUTE, 60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请稍后再试",
        )


async def chat_rate_limit(
    request: Request, current_user: User = Depends(get_current_user)
) -> None:
    """对话限流：按用户，防刷接口导致 token 成本失控。"""
    if not settings.RATE_LIMIT_ENABLED:
        return
    key = f"rl:chat:{current_user.id}"
    if not await is_allowed(key, settings.RATE_LIMIT_CHAT_PER_MINUTE, 60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="对话请求过于频繁，请稍后再试",
        )
