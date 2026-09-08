"""登录失败锁定：连续失败达到上限后返回 423 锁定。

核心逻辑（record_failure / is_locked / clear_lock）在 app.utils.lockout 中，
底层依赖 Redis。这里用内存版替身（monkeypatch）模拟 Redis 行为，使其不依赖外部服务、
也不会因 Redis 不可用而随机失败。登录成功的清除逻辑同样验证。
"""
from app.routers import auth as auth_module


class FakeLock:
    """内存版锁定状态机，复刻 lockout 的阈值与清除语义。"""

    def __init__(self, max_attempts: int = 5):
        self.failures: dict[str, int] = {}
        self.locked: dict[str, int] = {}
        self.max = max_attempts

    async def is_locked(self, identifier: str):
        return self.locked.get(identifier)

    async def record_failure(self, identifier: str, ip: str):
        self.failures[identifier] = self.failures.get(identifier, 0) + 1
        if self.failures[identifier] >= self.max:
            self.locked[identifier] = 900  # 模拟剩余锁定秒数

    async def clear_lock(self, identifier: str):
        self.failures.pop(identifier, None)
        self.locked.pop(identifier, None)


def _register_and_login(client, username="alice", password="secret123"):
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    r = client.post("/api/v1/auth/login", data={"username": username, "password": password})
    return r.json()["access_token"]


def test_lockout_after_repeated_failures(client, monkeypatch):
    fl = FakeLock(max_attempts=5)
    monkeypatch.setattr(auth_module, "is_locked", fl.is_locked)
    monkeypatch.setattr(auth_module, "record_failure", fl.record_failure)
    monkeypatch.setattr(auth_module, "clear_lock", fl.clear_lock)
    # 让认证恒失败（模拟错误密码）
    monkeypatch.setattr(
        auth_module, "authenticate_user", lambda db, identifier, password: None
    )

    # 前 5 次失败都是 401
    for i in range(5):
        r = client.post("/api/v1/auth/login", data={"username": "victim", "password": "x"})
        assert r.status_code == 401, (i, r.text)

    # 第 6 次应被锁定
    r = client.post("/api/v1/auth/login", data={"username": "victim", "password": "x"})
    assert r.status_code == 423


def test_success_clears_lock(client, monkeypatch, db):
    """真实用户登录成功后应清除失败计数（之后不会立刻被锁定）。"""
    fl = FakeLock(max_attempts=2)
    monkeypatch.setattr(auth_module, "is_locked", fl.is_locked)
    monkeypatch.setattr(auth_module, "record_failure", fl.record_failure)
    monkeypatch.setattr(auth_module, "clear_lock", fl.clear_lock)

    _register_and_login(client, username="bob", password="secret123")

    # 故意错 1 次（未达阈值，不锁定）
    r = client.post("/api/v1/auth/login", data={"username": "bob", "password": "wrong"})
    assert r.status_code == 401

    # 正确密码登录成功，且清除了失败计数
    r = client.post("/api/v1/auth/login", data={"username": "bob", "password": "secret123"})
    assert r.status_code == 200
    assert fl.failures.get("bob") is None
    assert fl.locked.get("bob") is None
