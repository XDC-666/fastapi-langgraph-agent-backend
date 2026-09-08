"""对话路由：非流式 / 流式（SSE）。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.message import Message
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import assemble_input, get_agent_graph, run_chat

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """非流式对话：一次性返回完整回复。"""
    conv_id, reply = run_chat(
        db, current_user.id, payload.message, payload.conversation_id, payload.use_knowledge
    )
    if conv_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=reply)
    return ChatResponse(conversation_id=conv_id, reply=reply)


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流式对话：以 SSE 形式逐 token 返回。

    返回的事件格式：
      data: {"delta": "文本片段"}
      data: {"done": true, "conversation_id": 1}
      data: {"error": "错误信息"}
    """

    async def event_generator():
        conv, lang_messages = assemble_input(
            db, current_user.id, payload.message, payload.conversation_id, payload.use_knowledge
        )
        if conv is None:
            yield f"data: {json.dumps({'error': '会话不存在或无权访问'}, ensure_ascii=False)}\n\n"
            return

        graph = get_agent_graph()
        full_reply = ""
        try:
            async for step in graph.astream({"messages": lang_messages}, stream_mode="updates"):
                for node, update in step.items():
                    if node == "agent":
                        msg = update["messages"][-1]
                        if (
                            hasattr(msg, "content")
                            and isinstance(msg.content, str)
                            and msg.content
                        ):
                            full_reply += msg.content
                            yield f"data: {json.dumps({'delta': msg.content}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            return

        # 流结束后落库
        db.add(Message(conversation_id=conv.id, role="user", content=payload.message))
        db.add(Message(conversation_id=conv.id, role="assistant", content=full_reply))
        db.commit()
        yield f"data: {json.dumps({'done': True, 'conversation_id': conv.id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
