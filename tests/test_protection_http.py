"""HTTP 层的防护回归：限流 429、X-Forwarded-For 处理、跨用户隔离。

已有的 tests/test_rate_limit.py 是**单元级**（直接调 is_allowed 函数），
这里补的是**端到端**：请求真的通过路由、依赖、中间件，最终返回 429 / 404 / 200。
单元通过但接线断掉（依赖没挂、别名没改）的情况，只有端到端能发现。
"""
from app.utils import rate_limit


class FakeRedis:
    """仅实现本项目用到的 INCR / EXPIRE 语义，用于端到端触发限流。"""

    def __init__(self):
        self.store: dict[str, int] = {}
        self.keys_captured: list[str] = []

    async def incr(self, key: str):
        self.keys_captured.append(key)
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, seconds: int):
        return True


def _login_and_token(client, username, password):
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    r = client.post("/api/v1/auth/login", data={"username": username, "password": password})
    return r.json()["access_token"]


def test_chat_rate_limit_returns_429_over_http(client, fake_graph, monkeypatch):
    """对话配额用尽后，HTTP 层必须真的返回 429（而不是 200 或 500）。"""
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "redis_client", fake)
    monkeypatch.setattr(rate_limit.settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(rate_limit.settings, "RATE_LIMIT_CHAT_PER_MINUTE", 3)

    token = _login_and_token(client, "limitee", "RateLimit123!")
    auth = {"Authorization": f"Bearer {token}"}

    codes = []
    for _ in range(5):
        r = client.post("/api/v1/chat", json={"message": "hi"}, headers=auth)
        codes.append(r.status_code)

    assert codes[:3] == [200, 200, 200]
    assert set(codes[3:]) == {429}
    # 限流按用户维度，key 里必须带 user id
    assert any(k.startswith("rl:chat:") for k in fake.keys_captured)


def test_login_rate_limit_returns_429_over_http(client, monkeypatch):
    """登录配额用尽后返回 429（按 IP，防暴力破解）。"""
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "redis_client", fake)
    monkeypatch.setattr(rate_limit.settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(rate_limit.settings, "RATE_LIMIT_LOGIN_PER_MINUTE", 2)

    codes = []
    for _ in range(4):
        r = client.post(
            "/api/v1/auth/login", data={"username": "someone", "password": "whatever"}
        )
        codes.append(r.status_code)

    assert set(codes[2:]) == {429}
    assert any(k.startswith("rl:login:") for k in fake.keys_captured)


def test_x_forwarded_for_ignored_when_proxy_untrusted(client, monkeypatch):
    """TRUST_PROXY=False 时必须忽略 XFF，防止伪造该头绕过限流 / 嫁祸他人。"""
    monkeypatch.setattr(rate_limit.settings, "TRUST_PROXY", False)
    seen = {}

    async def _capture(key, limit, window):
        seen["key"] = key
        return True

    monkeypatch.setattr(rate_limit, "is_allowed", _capture)
    monkeypatch.setattr(rate_limit.settings, "RATE_LIMIT_ENABLED", True)

    client.post(
        "/api/v1/auth/login",
        data={"username": "x", "password": "y"},
        headers={"X-Forwarded-For": "9.9.9.9"},
    )
    assert seen["key"] == "rl:login:testclient", f"漏用了伪造 IP：{seen['key']}"


def test_x_forwarded_for_used_leftmost_when_proxy_trusted(client, monkeypatch):
    """TRUST_PROXY=True 时取 XFF 最左侧（原始客户端），而不是最近一跳的代理 IP。"""
    monkeypatch.setattr(rate_limit.settings, "TRUST_PROXY", True)
    seen = {}

    async def _capture(key, limit, window):
        seen["key"] = key
        return True

    monkeypatch.setattr(rate_limit, "is_allowed", _capture)
    monkeypatch.setattr(rate_limit.settings, "RATE_LIMIT_ENABLED", True)

    client.post(
        "/api/v1/auth/login",
        data={"username": "x", "password": "y"},
        headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"},
    )
    assert seen["key"] == "rl:login:1.1.1.1", f"未取最左原始 IP：{seen['key']}"


def test_other_users_conversation_is_404_not_403(client):
    """越权访问他人会话：404（不泄露资源存在性），而非 403。"""
    alice = _login_and_token(client, "alice", "AlicePass123!")
    bob = _login_and_token(client, "bobby", "BobbyPass123!")

    conv = client.post(
        "/api/v1/conversations", json={"title": "私密会话"}, headers={"Authorization": f"Bearer {alice}"}
    ).json()

    bob_auth = {"Authorization": f"Bearer {bob}"}
    assert client.get(f"/api/v1/conversations/{conv['id']}", headers=bob_auth).status_code == 404
    assert (
        client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=bob_auth).status_code
        == 404
    )
    # Bob 的列表里也不应出现 Alice 的会话
    listed = client.get("/api/v1/conversations", headers=bob_auth).json()
    assert [c["id"] for c in listed] == []
