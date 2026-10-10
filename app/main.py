"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, engine
from app.models import Conversation, Message, TokenUsage, User  # noqa: F401 注册 ORM 映射
from app.routers import auth, chat, conversations, health, knowledge, usage
from app.utils.cache import redis_client
from app.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("DEBUG" if settings.DEBUG else "INFO")
    # 开发环境一键建表；生产设 AUTO_CREATE_TABLES=false，改用 `alembic upgrade head`
    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)
    yield
    await redis_client.aclose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description=(
        "基于 FastAPI + LangGraph 的 AI Agent 后端服务，"
        "支持多轮对话、工具调用、RAG 知识库与流式输出。"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(usage.router)
app.include_router(health.router)

# 同源挂载演示前端，避免 file:// 打开导致相对 API 地址与 CORS 失效
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")


@app.get("/")
def root():
    return {
        "message": f"{settings.PROJECT_NAME} 已启动",
        "docs": "/docs",
        "frontend": "/app/",
        "health": f"{settings.API_V1_PREFIX}/health",
    }
