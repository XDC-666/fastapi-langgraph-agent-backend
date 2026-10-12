"""Redis 客户端、探活与熔断。

Redis 在本项目里是**辅助组件**（限流、登录失败锁定、缓存），不可用时上层一律
降级放行 —— 但这带来两个容易被忽略的延迟陷阱，这里逐条处理：

1. 不设超时：一次调用会挂到系统级 TCP 超时，认证链路被放大到秒级。
   → 连接池显式设置 socket_connect_timeout / socket_timeout，并关闭
     retry_on_timeout 防止单次请求被重复放大。

2. 只设超时：Redis 持续不可用时，一个业务操作会连锁触发多次调用，
   每次都付满超时 —— 一个登录要碰 2~3 次 Redis，1.5s 就进去了。
   → 连续失败达到阈值后熔断，冷却期内直接短路返回降级值，
     不再向一个已知不可用的服务发起注定失败的连接。
"""
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

redis_client: aioredis.Redis = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SECONDS,
    socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
    retry_on_timeout=False,
    health_check_interval=30,
)


class RedisCircuitBreaker:
    """简单熔断器：closed → open → half-open → closed。

    asyncio 单线程模型下用普通属性即可，无并发竞态；但多个协程会在同一段
    await 区间内交错执行，因此这里只做计数与时间戳判断，不加锁。
    """

    def __init__(self, failure_threshold: int, cooldown_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.consecutive_failures = 0
        self.opened_at: float | None = None
        # 观测用：累计被短路掉多少次调用
        self.short_circuit_count = 0

    @property
    def is_open(self) -> bool:
        """是否处于熔断态。冷却结束即转 half-open（放行下一次调用）。"""
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.cooldown_seconds:
            logger.info("Redis 冷却结束，转入半开态，放行一次真实探测")
            self.opened_at = None
            return False
        return True

    def record_success(self) -> None:
        """真实调用成功 → 立即闭合。"""
        if self.opened_at is not None or self.consecutive_failures:
            logger.info("Redis 探测成功，熔断器闭合")
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        """真实调用失败 → 计数；达到阈值打开熔断。"""
        self.consecutive_failures += 1
        if self.opened_at is None and self.consecutive_failures >= self.failure_threshold:
            self.opened_at = time.monotonic()
            logger.warning(
                "Redis 连续失败 %d 次达到阈值 %d，熔断 %.0fs；"
                "期间限流 / 登录锁定降级放行",
                self.consecutive_failures, self.failure_threshold, self.cooldown_seconds,
            )

    def reset(self) -> None:
        """恢复到初始闭合态（测试隔离用）。"""
        self.consecutive_failures = 0
        self.opened_at = None
        self.short_circuit_count = 0


breaker = RedisCircuitBreaker(
    failure_threshold=settings.REDIS_CIRCUIT_FAILURE_THRESHOLD,
    cooldown_seconds=settings.REDIS_CIRCUIT_COOLDOWN_SECONDS,
)


async def redis_call(
    operation: str,
    call: Callable[[], Awaitable[T]],
    fallback: T,
) -> T:
    """执行 Redis 调用，统一处理熔断与降级。

    Args:
        operation: 操作名，仅用于日志定位。
        call: 无参协程工厂。**必须是延迟执行的工厂而非协程对象**，这样
              熔断短路时可以完全不建立连接，也便于测试 monkeypatch 掉
              `redis_client` 后立即生效。
        fallback: 熔断或异常时的降级返回值。

    Returns:
        真实结果，或降级值 fallback。
    """
    if settings.REDIS_CIRCUIT_ENABLED and breaker.is_open:
        breaker.short_circuit_count += 1
        # 短路是高频事件，只打 debug，避免每次请求都刷 warning 淹没日志
        logger.debug("Redis 熔断中，短路调用 %s（累计短路 %d 次）",
                     operation, breaker.short_circuit_count)
        return fallback

    try:
        result = await call()
    except Exception as exc:  # noqa: BLE001
        # Redis 是辅助组件：失败不阻断业务，但要记账以便熔断
        if settings.REDIS_CIRCUIT_ENABLED:
            breaker.record_failure()
        logger.warning("Redis 调用失败（%s）：%s，本次降级处理", operation, exc)
        return fallback
    else:
        breaker.record_success()
        return result


async def ping() -> bool:
    """探测 Redis 是否可用。

    熔断打开时直接返回 False —— 这并非偷懒：刚连续失败多次本身就是
    「Redis 不可用」的最新证据，且免去每次健康检查都付一次连接超时。
    """
    return await redis_call("ping", redis_client.ping, fallback=False)
