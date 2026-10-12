"""Redis 熔断器回归。

背景：Redis 在本项目是辅助组件，不可用时降级放行。但「降级」只保证了
**正确性**，延迟仍然会被放大 —— 超时能保证单次调用不死等，却挡不住
一个业务操作连锁触发多次调用：一次登录要碰 is_locked / clear_lock，
限流再叠一次，每次都付满超时就把接口拖到秒级。

熔断器补的是这件事：连续失败后短期内不再向已知不可用的服务发起
注定失败的连接。下面这些断言把这个机制钉死，防止被改回无熔断写法。
"""
import asyncio
import time

import pytest

from app.utils import cache


@pytest.fixture()
def breaker_isolated():
    """提供状态干净的熔断器，并在用例结束时复位。

    刻意**不用 autouse**：整套测试跑在无 Redis 环境，正是靠 session 级共享的
    熔断状态把大量登录用例的超时开销压下去。若每个用例都复位，
    套件耗时会退回熔断前的水平。
    """
    b = cache.breaker
    saved = (b.consecutive_failures, b.opened_at, b.short_circuit_count,
             b.failure_threshold, b.cooldown_seconds)
    b.reset()
    b.failure_threshold = 3
    b.cooldown_seconds = 30.0
    yield b
    b.consecutive_failures, b.opened_at = saved[0], saved[1]
    b.short_circuit_count = saved[2]
    b.failure_threshold, b.cooldown_seconds = saved[3], saved[4]


async def _fail(barrier):
    barrier.append(1)
    raise ConnectionError("redis is down")


async def _hang(barrier):
    """模拟「连不上又不立刻失败」：挂满连接超时的真实体感。"""
    barrier.append(1)
    await asyncio.sleep(10)


async def test_breaker_opens_after_consecutive_failures(breaker_isolated):
    """连续失败达到阈值 → 熔断打开；未达阈值前不应误伤。"""
    b = breaker_isolated
    calls: list = []

    await cache.redis_call("t", lambda: _fail(calls), fallback=None)
    assert b.is_open is False, "第 1 次失败就熔断，阈值形同虚设"
    await cache.redis_call("t", lambda: _fail(calls), fallback=None)
    assert b.is_open is False

    await cache.redis_call("t", lambda: _fail(calls), fallback=None)
    assert b.is_open is True, "达到阈值 3 次仍未熔断"
    assert len(calls) == 3


async def test_short_circuit_skips_call_completely(breaker_isolated):
    """熔断期间必须**根本不发起调用**，而不是发起了再快速失败。"""
    b = breaker_isolated
    calls: list = []
    for _ in range(3):
        await cache.redis_call("t", lambda: _fail(calls), fallback=None)
    assert b.is_open is True

    calls.clear()
    budget = 0.2
    start = time.perf_counter()
    result = await cache.redis_call("t-slow", lambda: _hang(calls), fallback="降级值")
    elapsed = time.perf_counter() - start

    assert calls == [], f"熔断期间仍发起了 {len(calls)} 次真实调用"
    assert result == "降级值"
    assert elapsed < budget, f"短路耗时 {elapsed:.3f}s，未走熔断而是等了真实调用"


async def test_failures_before_threshold_do_not_accumulate_forever(breaker_isolated):
    """偶发失败不应累积成熔断：成功一次即把连续失败计数清零。"""
    b = breaker_isolated
    calls: list = []

    for i in range(b.failure_threshold - 1):
        await cache.redis_call("t", lambda: _fail(calls), fallback=None)
        assert b.consecutive_failures == i + 1

    await cache.redis_call("t", lambda: asyncio.sleep(0), fallback=None)
    assert b.consecutive_failures == 0, "成功后未清零，偶发抖动会被累积成误熔断"

    # 再来同样次数的偶发失败，仍不应熔断
    for _ in range(b.failure_threshold - 1):
        await cache.redis_call("t", lambda: _fail(calls), fallback=None)
    assert b.is_open is False


async def test_half_open_after_cooldown_then_success_closes(breaker_isolated):
    """冷却结束转半开，放行一次真实探测；成功后彻底闭合。"""
    b = breaker_isolated
    calls: list = []
    for _ in range(3):
        await cache.redis_call("t", lambda: _fail(calls), fallback=None)
    assert b.is_open is True

    b.cooldown_seconds = 0  # 冷却立即到期
    assert b.is_open is False, "冷却结束后未转入半开"

    result = await cache.redis_call("t", lambda: asyncio.sleep(0, result="真实值"), fallback=None)
    assert result == "真实值", "半开态未放行真实调用"
    assert b.is_open is False and b.consecutive_failures == 0


async def test_ping_is_false_and_instant_when_circuit_open(breaker_isolated):
    """健康检查在熔断期间直接报 down：不付超时，语义也是对的。"""
    b = breaker_isolated
    for _ in range(3):
        await cache.redis_call("t", lambda: _fail([]), fallback=None)
    assert b.is_open is True

    budget = 0.2
    start = time.perf_counter()
    result = await cache.ping()
    elapsed = time.perf_counter() - start

    assert result is False
    assert elapsed < budget, f"熔断期间 ping 耗时 {elapsed:.3f}s，疑似仍在做真实连接"


async def test_circuit_disabled_falls_back_to_plain_timeout(monkeypatch, breaker_isolated):
    """REDIS_CIRCUIT_ENABLED=False 时应完全绕过熔断（保留运维逃生开关）。"""
    monkeypatch.setattr(cache.settings, "REDIS_CIRCUIT_ENABLED", False)
    calls: list = []
    for _ in range(5):
        await cache.redis_call("t", lambda: _fail(calls), fallback=None)

    assert len(calls) == 5, "关闭熔断后不应生效，所有调用都应真实发出"
    assert cache.breaker.consecutive_failures == 0, "关闭熔断期间不应记账"
