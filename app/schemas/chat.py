"""对话相关 Schema。"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """发送一条对话消息。"""

    message: str = Field(..., description="用户输入内容")
    conversation_id: int | None = Field(None, description="不传则新建会话")
    use_knowledge: bool = Field(False, description="是否使用知识库 RAG 检索")


class ChatResponse(BaseModel):
    """对话响应。"""

    conversation_id: int
    reply: str
