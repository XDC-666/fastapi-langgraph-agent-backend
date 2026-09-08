"""Token 用量统计：捕获逻辑与聚合接口。

注意：测试用的 FakeGraph 不产出 usage_metadata，因此不会写用量记录；
这里直接对 usage_service 做单元验证，并用真实 DB 验证 /usage/me 聚合接口能正常返回。
"""
from types import SimpleNamespace

from langchain_core.messages import AIMessage, UsageMetadata

from app.services.usage_service import extract_token_usage, get_usage_summary, record_token_usage


def test_extract_token_usage_handles_both_field_names():
    # 新字段名（langchain 实际产出，UsageMetadata 要求 input/output/total_tokens）
    new_style = AIMessage(
        content="hi",
        usage_metadata=UsageMetadata(input_tokens=5, output_tokens=7, total_tokens=12),
    )
    assert extract_token_usage(new_style) == (5, 7, 12)

    # 兼容旧字段名 prompt_tokens/completion_tokens（某些 SDK 或自定义 dict 仍可能产出）：
    # 用 SimpleNamespace 模拟 message 对象，绕过 AIMessage 对 usage_metadata 的 TypedDict 校验
    old_style = SimpleNamespace(
        usage_metadata={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    )
    assert extract_token_usage(old_style) == (10, 20, 30)

    # 无 usage_metadata 返回 None
    assert extract_token_usage(AIMessage(content="hi")) is None


def test_record_and_summary(db):
    user_id = 1
    record_token_usage(db, user_id, 10, "gpt-4o-mini", 100, 50)
    record_token_usage(db, user_id, 10, "gpt-4o-mini", 200, 80)

    summary = get_usage_summary(db, user_id, days=30)
    assert summary["request_count"] == 2
    assert summary["total_prompt_tokens"] == 300
    assert summary["total_completion_tokens"] == 130
    assert summary["total_tokens"] == 430
    # gpt-4o-mini 在价格表中，应有成本估算
    assert summary["by_model"][0]["model"] == "gpt-4o-mini"
    assert summary["by_model"][0]["cost_usd"] is not None
    # 未知模型成本应为 None
    record_token_usage(db, user_id, 11, "some-unknown-model", 1, 1)
    summary2 = get_usage_summary(db, user_id, days=30)
    unknown = next(m for m in summary2["by_model"] if m["model"] == "some-unknown-model")
    assert unknown["cost_usd"] is None


def test_usage_me_endpoint_returns_200(client, fake_graph, db):
    token = _login(client)
    r = client.get("/api/v1/usage/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_tokens"] == 0
    assert body["by_model"] == []


def _login(client, username="carol", password="secret123"):
    client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    r = client.post("/api/v1/auth/login", data={"username": username, "password": password})
    return r.json()["access_token"]
