"""Health endpoint must not run synchronous DB I/O on the event loop."""
import pytest

from app.routers import health as health_module


@pytest.mark.asyncio
async def test_health_offloads_database_probe(monkeypatch):
    calls = []

    def fake_check_database():
        return True

    async def fake_run_in_threadpool(func, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    async def fake_ping():
        return False

    monkeypatch.setattr(health_module, "check_database", fake_check_database)
    monkeypatch.setattr(health_module, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(health_module, "ping", fake_ping)

    result = await health_module.health()

    assert calls == [fake_check_database]
    assert result == {"status": "degraded", "database": True, "redis": False}
