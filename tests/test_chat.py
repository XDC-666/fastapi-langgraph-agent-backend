"""认证 / 对话 / 流式 / 历史窗口 的集成测试。

重点覆盖：
- 注册 → 登录 → 鉴权访问 的完整链路
- 流式接口（SSE）能产出 token 增量并正确落库
- 对话历史窗口限制生效（防止长对话 token 超限）
- 计算器工具的注入 / DoS 防护回归
"""
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.agent.tools import calculator
from app.services.chat_service import build_history_messages
from tests.conftest import parse_sse


def register_and_login(client, username="alice", password="secret123"):
    r = client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert r.status_code == 201, r.text
    # 登录走 OAuth2 密码流，必须是 form 表单而非 JSON
    r = client.post(
        "/api/v1/auth/login", data={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_register_login_and_me(client):
    token = register_and_login(client)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_protected_route_requires_auth(client):
    r = client.post("/api/v1/chat", json={"message": "hi"})
    assert r.status_code == 401


def test_chat_stream_emits_deltas_and_persists(client, fake_graph, db):
    """流式接口：应产出多个 delta 增量、done 事件，并把问答写入数据库。"""
    token = register_and_login(client)
    r = client.post(
        "/api/v1/chat/stream",
        json={"message": "你好"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    events = parse_sse(r.text)
    deltas = [e["delta"] for e in events if "delta" in e]
    assert deltas == ["你", "好", "，", "世界"], deltas

    done = [e for e in events if e.get("done")]
    assert len(done) == 1
    conv_id = done[0]["conversation_id"]

    rows = (
        db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.id).all()
    )
    assert [(m.role, m.content) for m in rows] == [
        ("user", "你好"),
        ("assistant", "你好，世界"),
    ]


def test_chat_stream_rejects_foreign_conversation(client, fake_graph, db):
    """访问他人会话应返回 error 事件，而不是把内容写进别人的会话。"""
    token = register_and_login(client, username="alice")
    # 手动造一个不属于 alice 的会话
    other = Conversation(owner_id=9999, title="别人的会话")
    db.add(other)
    db.commit()

    r = client.post(
        "/api/v1/chat/stream",
        json={"message": "你好", "conversation_id": other.id},
        headers={"Authorization": f"Bearer {token}"},
    )
    events = parse_sse(r.text)
    assert any("error" in e for e in events)


def test_chat_non_stream_returns_404_on_bad_conversation(client, fake_graph):
    """回归：此前 chat.py 漏 import status，该分支会抛 NameError 变 500。"""
    token = register_and_login(client, username="bob")
    r = client.post(
        "/api/v1/chat",
        json={"message": "hi", "conversation_id": 999999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, f"期望 404，实际 {r.status_code}"


def test_history_window_limits_messages(db):
    """历史只取最近 N 条，避免长对话撑爆上下文窗口。"""
    conv = Conversation(owner_id=1, title="长对话")
    db.add(conv)
    db.commit()

    total = 30
    for i in range(total):
        db.add(Message(conversation_id=conv.id, role="user", content=f"u{i}"))
        db.add(Message(conversation_id=conv.id, role="assistant", content=f"a{i}"))
    db.commit()

    from app.config import settings

    msgs = build_history_messages(db, conv.id)
    assert len(msgs) == settings.MAX_HISTORY_MESSAGES
    # 取的是「最近」的：最后一条应是最后插入的 assistant 消息
    assert msgs[-1].content == f"a{total - 1}"
    assert msgs[0].content == f"u{total - settings.MAX_HISTORY_MESSAGES // 2}"


def test_run_chat_persists_and_returns(client, fake_graph, db):
    token = register_and_login(client, username="carol")
    r = client.post(
        "/api/v1/chat",
        json={"message": "讲个笑话"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "你好，世界"
    assert body["conversation_id"] > 0


def test_calculator_blocks_injection_and_dos():
    """回归：计算器不得被 RCE，也不得被超大指数拖垮。"""
    assert "7" in calculator.invoke("1 + 2 * 3")
    assert "非法" in calculator.invoke("__import__('os').system('echo hacked')") or \
           "不支持" in calculator.invoke("__import__('os').system('echo hacked')")
    assert "过大" in calculator.invoke("2**99999999") or \
           "失败" in calculator.invoke("2**99999999") or \
           "不支持" in calculator.invoke("2**99999999")
