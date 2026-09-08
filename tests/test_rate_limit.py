"""限流组件的单元测试。

重点验证「降级」行为：Redis 不可用时必须放行，
绝不能因为限流组件故障导致登录/对话整体不可用。
"""
import pytest

from app.utils import rate_limit


@pytest.mark.asyncio
async def test_is_allowed_passes_when_redis_down(monkeypatch):
    """Redis 抛异常时应降级放行，而不是让请求失败。"""

    async def _boom(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(rate_limit.redis_client, "incr", _boom)
    assert await rate_limit.is_allowed("rl:test:1", limit=1, window_seconds=60) is True


@pytest.mark.asyncio
async def test_is_allowed_blocks_after_limit(monkeypatch):
    """超过额度后应拒绝。用内存计数器模拟 Redis INCR。"""
    store = {}

    async def _incr(key):
        store[key] = store.get(key, 0) + 1
        return store[key]

    async def _expire(key, seconds):
        return True

    monkeypatch.setattr(rate_limit.redis_client, "incr", _incr)
    monkeypatch.setattr(rate_limit.redis_client, "expire", _expire)

    assert await rate_limit.is_allowed("rl:ip:1.2.3.4", limit=2, window_seconds=60) is True
    assert await rate_limit.is_allowed("rl:ip:1.2.3.4", limit=2, window_seconds=60) is True
    assert await rate_limit.is_allowed("rl:ip:1.2.3.4", limit=2, window_seconds=60) is False


@pytest.mark.asyncio
async def test_login_rate_limit_disabled_is_noop(monkeypatch):
    """关闭限流时依赖应直接返回，不触碰 Redis。"""
    monkeypatch.setattr(rate_limit.settings, "RATE_LIMIT_ENABLED", False)

    called = False

    class FakeRedis:
        async def incr(self, key):
            nonlocal called
            called = True
            return 1

    monkeypatch.setattr(rate_limit, "redis_client", FakeRedis())
    # Request 参数在关闭时不会被使用，传 None 即可
    await rate_limit.login_rate_limit(None)  # type: ignore[arg-type]
    assert called is False
