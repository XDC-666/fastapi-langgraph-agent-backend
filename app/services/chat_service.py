"""对话业务逻辑：会话管理、历史加载、调用 Agent、持久化。"""
from langchain_core.messages import AIMessage, HumanMessage

from app.models.conversation import Conversation
from app.models.message import Message
from app.services.agent.graph import build_graph

# 编译后的图做全局缓存，避免每次请求重复编译
_agent_graph = None


def get_agent_graph():
    """返回（并缓存）编译后的 Agent 图。"""
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_graph()
    return _agent_graph


def get_or_create_conversation(db, user_id: int, conversation_id: int | None) -> Conversation | None:
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
    """从数据库加载该会话历史，转为 LangChain 消息对象。"""
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id)
        .all()
    )
    messages = []
    for m in rows:
        if m.role == "user":
            messages.append(HumanMessage(content=m.content))
        else:
            messages.append(AIMessage(content=m.content))
    return messages


def assemble_input(db, user_id: int, message: str, conversation_id: int | None, use_knowledge: bool):
    """整合会话、历史、用户消息，返回 (conversation, langchain_messages)。"""
    conv = get_or_create_conversation(db, user_id, conversation_id)
    if conv is None:
        return None, None

    history = build_history_messages(db, conv.id)
    user_msg = HumanMessage(content=message)

    if use_knowledge:
        # 延迟导入，避免循环依赖
        from app.services.knowledge_service import retrieve_for_query

        context = retrieve_for_query(message)
        if context:
            user_msg = HumanMessage(
                content=f"请结合以下知识回答用户问题：\n\n{context}\n\n用户问题：{message}"
            )
    return conv, history + [user_msg]


def run_chat(db, user_id: int, message: str, conversation_id: int | None, use_knowledge: bool = False):
    """非流式对话：返回 (conversation_id, reply)；会话非法返回 (None, 错误信息)。"""
    conv, lang_messages = assemble_input(db, user_id, message, conversation_id, use_knowledge)
    if conv is None:
        return None, "会话不存在或无权访问"

    result = get_agent_graph().invoke({"messages": lang_messages})
    reply = result["messages"][-1].content

    db.add(Message(conversation_id=conv.id, role="user", content=message))
    db.add(Message(conversation_id=conv.id, role="assistant", content=reply))
    db.commit()
    return conv.id, reply
