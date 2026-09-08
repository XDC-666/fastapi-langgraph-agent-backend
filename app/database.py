"""数据库引擎与会话管理。

这里使用 SQLAlchemy 2.0 的 DeclarativeBase 风格。
get_db 是 FastAPI 依赖，每个请求创建一个会话并在结束后关闭。
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# 创建同步引擎（pool_pre_ping 会在每次使用前检测连接是否存活）
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

# 会话工厂
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    pass


def get_db():
    """FastAPI 依赖：提供数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
