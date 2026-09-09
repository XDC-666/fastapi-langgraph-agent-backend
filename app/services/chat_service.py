"""对话业务逻辑：会话管理、历史加载、调用 Agent、持久化。"""
import logging

from langchain_core.messages import AIMessage, HumanMessage

from app.config import settings
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.agent.checkpointer import get_checkpointer
from app.services.agent.graph import build_graph
from app.services.usage_service import extract_token_usage, record_token_usage

logger = logging.getLogger(__name__)

# 编译后的图做全局缓存，避免每次请求重复编译
_agent_graph = None


def get_agent_graph():
    """返回（并缓存）编译后的 Agent 图（已接入 checkpointer）。"""
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_graph(get_checkpointer())
    return _agent_graph


def get_or_create_conversation(
    db, user_id: int, conversation_id: int | None
) -> Conversation | None:
    """按 id 取会话，或为用户新建会话；越权/不存在返回 None。"""
    if conversation_id:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.owner_id != user_id:
            return None
        return conv
    conv = Conversation(owner_id=user_id, title="新对话")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def build_history_messages(db, conversation_id: int) -> list:
    """从数据库加载该会话最近的历史，转为 LangChain 消息对象。

    只取最近 `MAX_HISTORY_MESSAGES` 条：长对话若全量携带会迅速耗尽上下文窗口，
    并显著抬高 token 成本。生产环境更严谨的做法是按 token 数裁剪或做摘要。
    """
    limit = settings.MAX_HISTORY_MESSAGES
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
        .all()
    )
    messages = []
    # 上面按 id 倒序取，这里反转回正常时间顺序
    for m in reversed(rows):
        if m.role == "user":
            messages.append(HumanMessage(content=m.content))
        else:
            messages.append(AIMessage(content=m.content))
    return messages


def prepare_thread(graph, conversation_id: int) -> None:
    """为「本轮对话」准备 checkpointer 线程。

    以 conversation_id 作为 thread_id。由于 DB 才是权威持久化源且已做窗口裁剪，
    这里每轮先把该线程清空、再用最近 N 条历史重新播种，使 checkpointer 长度有界，
    避免长对话下 token 成本无限制增长（这是 Agent 工作记忆视图，而非审计源）。
    不支持 delete_thread 的 checkpointer 则跳过（退化为纯追加）。
    """
    cp = getattr(graph, "checkpointer", None)
    if cp is not None and hasattr(cp, "delete_thread"):
        try:
            cp.delete_thread(str(conversation_id))
        except Exception:  # noqa: BLE001
            logger.debug("delete_thread 失败，将直接追加到已有状态", exc_info=True)


def assemble_input(
    db, user_id: int, message: str, conversation_id: int | None, use_knowledge: bool
):
    """整合会话、历史、用户消息，返回 (conversation, langchain_messages, config)。

    config 携带 thread_id，供 LangGraph checkpointer 区分不同会话的状态。
    """
    conv = get_or_create_conversation(db, user_id, conversation_id)
    if conv is None:
        return None, None, None

    history = build_history_messages(db, conv.id)
    user_msg = HumanMessage(content=message)

    if use_knowledge:
        # 延迟导入，避免循环依赖
        from app.services.knowledge_service import retrieve_for_query

        context = retrieve_for_query(message, owner_id=user_id)
        if context:
            user_msg = HumanMessage(
                content=f"请结合以下知识回答用户问题：\n\n{context}\n\n用户问题：{message}"
            )

    config = {"configurable": {"thread_id": str(conv.id)}}
    return conv, history + [user_msg], config


def run_chat(
    db,
    user_id: int,
    message: str,
    conversation_id: int | None,
    use_knowledge: bool = False,
):
    """非流式对话：返回 (conversation_id, reply)；会话非法返回 (None, 错误信息)。"""
    conv, lang_messages, config = assemble_input(
        db, user_id, message, conversation_id, use_knowledge
    )
    if conv is None:
        return None, "会话不存在或无权访问"

    graph = get_agent_graph()
    prepare_thread(graph, conv.id)
    result = graph.invoke({"messages": lang_messages}, config)
    reply = result["messages"][-1].content

    # 记录 token 用量（仅当模型返回 usage 时）
    usage = extract_token_usage(result["messages"][-1])
    if usage:
        record_token_usage(db, user_id, conv.id, settings.LLM_MODEL, usage[0], usage[1])

    db.add(Message(conversation_id=conv.id, role="user", content=message))
    db.add(Message(conversation_id=conv.id, role="assistant", content=reply))
    db.commit()
    logger.info("对话完成 conversation_id=%s user_id=%s", conv.id, user_id)
    return conv.id, reply
