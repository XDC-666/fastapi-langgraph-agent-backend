"""基础冒烟测试：不依赖外部服务，仅校验应用可被导入且路由已注册。"""
from app.main import app


def test_app_importable():
    assert app.title == "fastapi-langgraph-agent-backend"


def test_routes_registered():
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/chat/stream" in paths
    assert "/api/v1/conversations" in paths
    assert "/api/v1/knowledge/upload" in paths
