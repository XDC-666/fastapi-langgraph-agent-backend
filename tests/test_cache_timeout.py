"""Redis 客户端超时配置回归。

为什么要这个测试：
Redis 在本项目里是**辅助组件**（限流、失败锁定、缓存），不可用时上层会降级放行。
但「降级」不等于「可以无限等待」：如果不显式设置连接 / 读写超时，一次调用会挂到
系统级 TCP 超时，把认证链路放大到数秒级。这两条断言把这个上限钉死，
防止有人改回 `aioredis.from_url(url)` 的无超时写法。
"""
import time

from app.config import get_settings
from app.utils.cache import ping, redis_client


def test_redis_client_has_explicit_timeouts():
    """连接池必须带上连接超时与读写超时，且来自配置（可运维调整）。"""
    settings = get_settings()
    kwargs = redis_client.connection_pool.connection_kwargs

    assert kwargs["socket_connect_timeout"] == settings.REDIS_CONNECT_TIMEOUT_SECONDS
    assert kwargs["socket_timeout"] == settings.REDIS_SOCKET_TIMEOUT_SECONDS
    # 超时必须是一个「有限且不大」的值，防止按秒级默认值退化
    assert 0 < kwargs["socket_connect_timeout"] <= 5
    assert 0 < kwargs["socket_timeout"] <= 5
    # 超时后不再自动重试，否则单请求会被重复放大
    assert kwargs.get("retry_on_timeout") is False


async def test_ping_fails_fast_when_redis_unreachable():
    """Redis 不可用时 ping 必须快速返回，而不是耗尽本次调用预算。"""
    budget = get_settings().REDIS_CONNECT_TIMEOUT_SECONDS * 4 + 1.0

    start = time.perf_counter()
    result = await ping()
    elapsed = time.perf_counter() - start

    # Redis 可用时返回 True，不可用时应抛出异常被吞掉返回 False
    assert isinstance(result, bool)
    assert elapsed < budget, f"ping 耗时 {elapsed:.2f}s，超过 {budget:.2f}s 预算（疑似未设超时）"
