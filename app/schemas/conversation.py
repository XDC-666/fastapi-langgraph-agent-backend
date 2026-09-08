"""会话与消息相关 Schema。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    """创建会话请求体。"""

    title: str | None = Field(None, max_length=255, description="会话标题，留空则自动生成")


class MessageOut(BaseModel):
    """单条消息响应。"""

    id: int
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationOut(BaseModel):
    """会话响应，含最近消息摘要。"""

    id: int
    title: str
    owner_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
