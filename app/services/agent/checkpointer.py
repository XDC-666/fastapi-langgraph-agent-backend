"""LangGraph Checkpointer 工厂。

Checkpointer 在多轮对话间保存 Agent 状态（消息列表）。
消息同时会落库到 messages 表（审计视角），两者职责不同、互不冲突。
"""
import logging

from langgraph.checkpoint.memory import MemorySaver

from app.config import settings

logger = logging.getLogger(__name__)


def get_checkpointer():
    """按 CHECKPOINTER_URI 返回 checkpointer 实例；默认内存版。"""
    uri = (settings.CHECKPOINTER_URI or "").strip()
    if uri.startswith("sqlite"):
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError:
            logger.warning(
                "CHECKPOINTER_URI 指向 sqlite 但未安装 langgraph-checkpoint-sqlite，"
                "已回退到 MemorySaver。请执行: pip install langgraph-checkpoint-sqlite"
            )
            return MemorySaver()
        # sqlite:///./data/checkpoints.sqlite -> ./data/checkpoints.sqlite
        path = uri.replace("sqlite:///", "").replace("sqlite://", "")
        logger.info("使用 SqliteSaver 持久化 checkpointer: %s", path)
        return SqliteSaver.from_conn_string(path)
    return MemorySaver()
