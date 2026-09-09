"""安全审计修复回归测试（对应 2026-09-10 安全审计报告）。

覆盖：
- HIGH：开启 use_knowledge 时，知识检索必须按 owner_id 隔离（防跨用户泄露）
- MEDIUM：限流取客户端 IP 在可信代理下取 X-Forwarded-For 最左地址，
          否则取直连（防限流失效 / 防伪造 X-Forwarded-For 绕过）
"""
from app.services.chat_service import assemble_input
from app.utils.rate_limit import _client_ip


# ---------- HIGH：跨用户知识库隔离 ----------

def test_chat_knowledge_isolation_per_user(db, monkeypatch):
    """use_knowledge=True 时，retrieve_for_query 必须收到当前 user_id，
    绝不能漏传 owner_id 导致全库检索、跨用户文档泄露。"""
    captured = {}

    def fake_retrieve(query, owner_id=None, k=3):
        captured["owner_id"] = owner_id
        captured["query"] = query
        return "【知识上下文】这是隔离后的内容"

    monkeypatch.setattr(
        "app.services.knowledge_service.retrieve_for_query", fake_retrieve
    )

    user_id = 42
    conv, messages, config = assemble_input(
        db, user_id, "有什么资料？", None, use_knowledge=True
    )
    assert conv is not None, "会话创建失败"
    assert captured.get("owner_id") == user_id, (
        f"知识检索未传 owner_id，实际为 {captured.get('owner_id')} "
        "—— 存在跨用户知识泄露（HIGH）"
    )
    # 用户消息应被注入隔离后的知识上下文
    assert any("【知识上下文】" in getattr(m, "content", "") for m in messages)


def test_chat_without_knowledge_skips_retrieval(db, monkeypatch):
    """未开启 use_knowledge 时不应调用知识检索（行为正确性 + 性能）。"""
    called = {"n": 0}

    def fake_retrieve(query, owner_id=None, k=3):
        called["n"] += 1
        return ""

    monkeypatch.setattr(
        "app.services.knowledge_service.retrieve_for_query", fake_retrieve
    )
    conv, messages, config = assemble_input(db, 1, "你好", None, use_knowledge=False)
    assert conv is not None
    assert called["n"] == 0


# ---------- MEDIUM：限流客户端 IP 提取 ----------

class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, host, xff=None):
        self.client = _FakeClient(host)
        self.headers = {}
        if xff is not None:
            self.headers["x-forwarded-for"] = xff


def test_client_ip_direct_connection():
    """直连（无代理）：取 request.client.host。"""
    assert _client_ip(_FakeRequest("203.0.113.9")) == "203.0.113.9"


def test_client_ip_uses_xff_when_trusted(monkeypatch):
    """可信代理后：取 X-Forwarded-For 最左（原始客户端）地址。"""
    monkeypatch.setattr("app.utils.rate_limit.settings.TRUST_PROXY", True)
    req = _FakeRequest("10.0.0.1", xff="198.51.100.7, 10.0.0.1, 10.0.0.2")
    assert _client_ip(req) == "198.51.100.7"


def test_client_ip_ignores_spoofed_xff_when_untrusted(monkeypatch):
    """不可信时：忽略伪造的 X-Forwarded-For，避免限流被绕过。"""
    monkeypatch.setattr("app.utils.rate_limit.settings.TRUST_PROXY", False)
    req = _FakeRequest("10.0.0.1", xff="198.51.100.7, 10.0.0.1")
    assert _client_ip(req) == "10.0.0.1"
