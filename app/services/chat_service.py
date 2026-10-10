"""对话业务逻辑：会话管理、历史加载、调用 Agent、持久化。"""
import logging

from fastapi.concurrency import run_in_threadpool
from langchain_core.messages import AIMessage, HumanMessage

from app.config import settings
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.usage import TokenUsage
from app.services.agent.checkpointer import get_checkpointer
from app.services.agent.graph import build_graph
from app.services.usage_service import extract_token_usage

logger = logging.getLogger(__name__)

# 编译后的图全局缓存，避免每次请求重复编译
_agent_graph = None


def get_agent_graph():
    """返回（并缓存）编译后的 Agent 图。"""
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
    """加载最近 MAX_HISTORY_MESSAGES 条历史，转为 LangChain 消息。

    只取最近 N 条，避免长对话撑爆上下文窗口、推高 token 成本。
    """
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(settings.MAX_HISTORY_MESSAGES)
        .all()
    )
    # 按 id 倒序取出后反转回时间顺序
    return [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in reversed(rows)
    ]


def prepare_thread(graph, conversation_id: int) -> None:
    """清空该会话的 checkpointer 线程，让每轮从 DB 裁剪后的历史重新开始。

    DB 是权威持久化源且已做窗口裁剪，这里清空可保证 checkpointer 长度有界；
    不支持 delete_thread 的实现直接跳过（退化为追加）。
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

    config 携带 thread_id，供 checkpointer 区分会话状态。
    """
    conv = get_or_create_conversation(db, user_id, conversation_id)
    if conv is None:
        return None, None, None

    history = build_history_messages(db, conv.id)
    user_msg = HumanMessage(content=message)

    if use_knowledge:
        # 延迟导入，避免与 knowledge_service 循环依赖
        from app.services.knowledge_service import retrieve_for_query

        context = retrieve_for_query(message, owner_id=user_id)
        if context:
            user_msg = HumanMessage(
                content=f"请结合以下知识回答用户问题：\n\n{context}\n\n用户问题：{message}"
            )

    return conv, history + [user_msg], {"configurable": {"thread_id": str(conv.id)}}


def persist_turn(
    db,
    user_id: int,
    conversation_id: int,
    user_content: str,
    assistant_content: str,
    usage: tuple[int, int, int] | None = None,
) -> None:
    """把一轮问答与聚合后的 token 用量写入数据库。"""
    db.add(Message(conversation_id=conversation_id, role="user", content=user_content))
    db.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_content,
        )
    )
    if usage:
        db.add(
            TokenUsage(
                user_id=user_id,
                conversation_id=conversation_id,
                model=settings.LLM_MODEL,
                prompt_tokens=usage[0],
                completion_tokens=usage[1],
                total_tokens=usage[2],
            )
        )
    db.commit()


async def run_chat(
    db,
    user_id: int,
    message: str,
    conversation_id: int | None,
    use_knowledge: bool = False,
):
    """非流式对话：同步 ORM 工作放线程池，返回 (conversation_id, reply)。"""
    conv, lang_messages, config = await run_in_threadpool(
        assemble_input, db, user_id, message, conversation_id, use_knowledge
    )
    if conv is None:
        return None, "会话不存在或无权访问"

    conv_id = conv.id
    graph = get_agent_graph()
    await run_in_threadpool(prepare_thread, graph, conv_id)
    result = await graph.ainvoke({"messages": lang_messages}, config)
    reply = result["messages"][-1].content

    usage = extract_token_usage(*result["messages"])
    await run_in_threadpool(
        persist_turn, db, user_id, conv_id, message, reply, usage
    )

    logger.info("对话完成 conversation_id=%s user_id=%s", conv_id, user_id)
    return conv_id, reply
