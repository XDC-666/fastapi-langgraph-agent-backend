"""FastAPI 应用入口。

启动时会自动建表（开发环境）；生产建议改用 Alembic 迁移。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.models import Conversation, Message, User  # noqa: F401 确保模型被注册
from app.routers import auth, chat, conversations, health, knowledge
from app.utils.cache import redis_client
from app.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("DEBUG" if settings.DEBUG else "INFO")
    # 开发环境自动建表
    Base.metadata.create_all(bind=engine)
    yield
    # 关闭时释放 Redis 连接（redis-py 5.0+ 推荐 aclose）
    await redis_client.aclose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description="基于 FastAPI + LangGraph 的 AI Agent 后端服务，支持多轮对话、工具调用、RAG 知识库与流式输出。",
    lifespan=lifespan,
)

# 允许跨域（前端联调需要）。生产环境请通过 CORS_ORIGINS 环境变量限定具体前端源，
# 不要用 "*"，避免任意网站跨域调用本 API。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(health.router)


@app.get("/")
def root():
    return {
        "message": f"{settings.PROJECT_NAME} 已启动",
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health",
    }
