"""基于 Redis 的接口限流。

设计要点：
- 固定窗口计数：INCR + EXPIRE，简单可靠、开销低。
- **降级放行**：Redis 不可用时直接放行，绝不让限流组件拖垮主流程
  （限流是保护性措施，不应成为新的故障点）。
- 可在配置里用 RATE_LIMIT_ENABLED 一键关闭（例如跑测试时）。
"""
import logging

from fastapi import Depends, HTTPException, Request, status

from app.config import settings
from app.dependencies import get_current_user
from app.models.user import User
from app.utils.cache import redis_client

logger = logging.getLogger(__name__)


async def is_allowed(key: str, limit: int, window_seconds: int) -> bool:
    """判断该 key 在当前窗口内是否还有额度。

    返回 True 表示放行。Redis 异常时同样返回 True（降级）。
    """
    try:
        count = await redis_client.incr(key)
        if count == 1:
            # 首次计数时才设置过期时间，保证是「固定窗口」而非不断续期
            await redis_client.expire(key, window_seconds)
        return count <= limit
    except Exception:  # noqa: BLE001
        logger.warning("限流组件不可用（Redis 异常），本次请求放行 key=%s", key)
        return True


def _client_ip(request: Request) -> str:
    """取客户端 IP 用于限流。

    - 直连或无代理：取 request.client.host。
    - 部署在可信反向代理（Nginx / 负载均衡）之后且 TRUST_PROXY=True 时：
      取 X-Forwarded-For 最左侧（原始客户端）地址，避免所有请求被记为代理 IP
      导致限流失效，也避免攻击者伪造 XFF 把限流嫁祸他人。
    - 不可信（默认）：忽略 X-Forwarded-For，屏蔽伪造头，保证限流基于真实直连 IP。
    """
    if settings.TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # 最左为原始客户端，其余为逐级代理，不可信
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
