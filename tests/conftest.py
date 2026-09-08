"""测试基础设施。

目标：让测试完全不依赖 PostgreSQL / Redis / 真实大模型 API。
- 数据库：内存 SQLite（StaticPool 保证跨线程复用同一连接）
- 大模型：通过 monkeypatch 注入 Fake 图对象
"""
import os

# 必须在导入 app 之前设置，否则配置会读取开发机的真实环境变量
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only"
os.environ["REQUIRE_SECRET_KEY"] = "false"
# 测试环境无 Redis，关闭限流（否则每个请求都要等 Redis 连接超时）
os.environ["RATE_LIMIT_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Conversation, Message, User  # noqa: F401,E402

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


@pytest.fixture()
def db():
    """每个用例一套干净的表结构。"""
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture()
def client(db, monkeypatch):
    """FastAPI 测试客户端：数据库指向内存 SQLite。"""
    # lifespan 里的 create_all 使用模块级 engine，这里替换掉
    monkeypatch.setattr("app.main.engine", TEST_ENGINE)

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class FakeGraph:
    """假的 LangGraph 图：模拟 Agent 产出，避免调用真实大模型。"""

    def __init__(self, chunks=("你", "好", "，", "世界"), reply="你好，世界"):
        self._chunks = list(chunks)
        self._reply = reply

    def invoke(self, state):
        return {"messages": [AIMessage(content=self._reply)]}

    async def astream(self, state, stream_mode=None):
        # 模拟 stream_mode="messages"：产出 (chunk, metadata) 元组
        for text in self._chunks:
            yield AIMessageChunk(content=text), {"langgraph_node": "agent"}
        # 模拟工具节点产生的、应被过滤掉的中间产物
        yield AIMessageChunk(content=""), {"langgraph_node": "tools"}


@pytest.fixture()
def fake_graph(monkeypatch):
    """把路由与 service 里的 get_agent_graph 都替换成 FakeGraph。"""
    graph = FakeGraph()
    monkeypatch.setattr("app.routers.chat.get_agent_graph", lambda: graph)
    monkeypatch.setattr("app.services.chat_service.get_agent_graph", lambda: graph)
    return graph


def parse_sse(body: str) -> list:
    """把 SSE 响应体解析成事件列表。"""
    events = []
    for raw in body.split("\n\n"):
        raw = raw.strip()
        if not raw or not raw.startswith("data:"):
            continue
        import json

        events.append(json.loads(raw[len("data:"):].strip()))
    return events
