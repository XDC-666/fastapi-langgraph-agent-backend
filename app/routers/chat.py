"""对话路由：非流式 / 流式（SSE）。"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.message import Message
from app.models.usage import TokenUsage
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import assemble_input, get_agent_graph, prepare_thread, run_chat
from app.services.usage_service import extract_token_usage
from app.utils.rate_limit import chat_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}", tags=["chat"])


def persist_turn(
    db: Session,
    user_id: int,
    conversation_id: int,
    user_content: str,
    assistant_content: str,
    usage: tuple[int, int, int] | None = None,
) -> None:
    """把一轮问答写入数据库，并可选记录 token 用量。

    同步 SQLAlchemy 会话不能直接 await，因此在 async 端点里由线程池调用本函数，
    避免阻塞事件循环（这是 FastAPI 中同步 ORM 的标准处理方式）。
    """
    db.add(Message(conversation_id=conversation_id, role="user", content=user_content))
    db.add(
        Message(conversation_id=conversation_id, role="assistant", content=assistant_content)
    )
    if usage:
        db.add(
            TokenUsage(
                user_id=user_id,
                conversation_id=conversation_id,
                model=settings.LLM_MODEL,
                prompt_tokens=usage[0],
                completion_tokens=usage[1],
                total_tokens=usage[0] + usage[1],
            )
        )
    db.commit()


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(chat_rate_limit)])
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


@router.post(
    "/chat/stream", dependencies=[Depends(chat_rate_limit)]
)
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
        # 同步 ORM 会阻塞事件循环，这里放到线程池执行，保证流式吞吐不受影响
        conv, lang_messages, config = await run_in_threadpool(
            assemble_input,
            db,
            current_user.id,
            payload.message,
            payload.conversation_id,
            payload.use_knowledge,
        )
        if conv is None:
            yield f"data: {json.dumps({'error': '会话不存在或无权访问'}, ensure_ascii=False)}\n\n"
            return

        graph = get_agent_graph()
        # 每轮重置该会话的 checkpointer 线程并用最近历史重新播种（有界、可恢复）
        await run_in_threadpool(prepare_thread, graph, conv.id)

        full_reply = ""
        usage = None  # (prompt, completion, total)
        try:
            # stream_mode="messages" 会产出 token 级增量 (chunk, metadata)
            async for chunk, metadata in graph.astream(
                {"messages": lang_messages}, config, stream_mode="messages"
            ):
                # 只取 agent 节点产生的文本增量，过滤工具调用等中间产物
                if metadata.get("langgraph_node") != "agent":
                    continue
                text = getattr(chunk, "content", None)
                if isinstance(text, str) and text:
                    full_reply += text
                    yield f"data: {json.dumps({'delta': text}, ensure_ascii=False)}\n\n"
                # 捕获 token 用量：流式时出现在最后一个 chunk 的 usage_metadata
                chunk_usage = extract_token_usage(chunk)
                if chunk_usage:
                    usage = chunk_usage
        except Exception as exc:  # noqa: BLE001
            logger.exception("流式对话失败")
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            return

        # 流结束后落库（消息 + token 用量），同样放线程池
        await run_in_threadpool(
            persist_turn, db, current_user.id, conv.id, payload.message, full_reply, usage
        )
        done_payload = {"done": True, "conversation_id": conv.id}
        yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
