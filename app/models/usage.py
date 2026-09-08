"""Token 用量记录模型。

每张表的一行代表一次对话请求消耗的 token，用于成本统计与审计。
user_id / conversation_id 允许为空（如匿名或异常场景），保证记录不丢失。
"""
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 归属用户（删除用户时级联删除其用量记录）
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 可空：删除会话时设为 NULL 而非级联删除（用量统计仍有价值）
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
