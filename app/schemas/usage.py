"""用量统计相关 Schema。"""
from pydantic import BaseModel


class ModelUsage(BaseModel):
    """按模型拆分的用量。"""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None  # 已知模型才有估算值


class DayUsage(BaseModel):
    """按天拆分的用量。"""

    day: str
    total_tokens: int


class UsageSummary(BaseModel):
    """当前用户的用量汇总。"""

    window_days: int
    request_count: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_usd: float | None
    by_model: list[ModelUsage]
    by_day: list[DayUsage]
