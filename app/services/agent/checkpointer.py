"""LangGraph Checkpointer 工厂。

Checkpointer 负责在多轮对话 / 工具调用之间保存 Agent 的「状态」（消息列表等），
让对话有记忆、可被恢复（get_state / update_state）。

- 默认 MemorySaver：进程内内存，零额外依赖，重启即清空，适合开发 / 单实例演示。
- 配置 CHECKPOINTER_URI=sqlite:///./data/checkpoints.sqlite 可落盘持久化，
  需要额外安装 langgraph-checkpoint-sqlite（懒导入，未安装时回退到 MemorySaver）。

注意：本项目同时把每条消息落库到 messages 表（审计 / 导出视角），
checkpointer 是 Agent 的工作记忆视图；两者职责不同、互不冲突。
"""
import logging

from langgraph.checkpoint.memory import MemorySaver

from app.config import settings

logger = logging.getLogger(__name__)


def get_checkpointer():
    """按配置返回 checkpointer 实例。"""
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
