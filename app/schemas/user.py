"""用户相关 Schema。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    """注册请求体。"""

    username: str = Field(..., min_length=3, max_length=50, description="用户名（3-50 字符）")
    email: str = Field(..., max_length=255, description="邮箱")
    password: str = Field(..., min_length=6, max_length=128, description="密码（至少 6 位）")


class UserLogin(BaseModel):
    """登录请求体（支持用户名或邮箱）。"""

    identifier: str = Field(..., description="用户名或邮箱")
    password: str = Field(..., description="密码")


class UserOut(BaseModel):
    """用户响应（不含密码）。"""

    id: int
    username: str
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
