"""Token 用量统计：从 LangChain 消息提取 usage，提供落库、聚合与成本估算。"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.usage import TokenUsage

# 已知模型的参考价格（美元 / 1M tokens），仅用于估算：(输入单价, 输出单价)
_MODEL_PRICES_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.150, 0.600),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-3.5-turbo": (0.50, 1.50),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
}


def merge_token_usage(
    current: tuple[int, int, int] | None,
    new: tuple[int, int, int] | None,
) -> tuple[int, int, int] | None:
    """按 (prompt, completion, total) 逐项累加。"""
    if current is None:
        return new
    if new is None:
        return current
    return (
        current[0] + new[0],
        current[1] + new[1],
        current[2] + new[2],
    )


def extract_token_usage(*messages) -> tuple[int, int, int] | None:
    """聚合消息上的 token 用量，全部消息都无 usage_metadata 时返回 None。

    一轮 Agent 可能因工具调用多次请求模型，所以逐条累加而不是只取最后一条。
    """
    usage = None
    for msg in messages:
        um = getattr(msg, "usage_metadata", None)
        if not um:
            continue
        prompt = um.get("prompt_tokens")
        if prompt is None:
            prompt = um.get("input_tokens", 0)
        completion = um.get("completion_tokens")
        if completion is None:
            completion = um.get("output_tokens", 0)
        total = um.get("total_tokens")
        if total is None:
            total = prompt + completion
        usage = merge_token_usage(usage, (prompt, completion, total))
    return usage


def record_token_usage(
    db: Session,
    user_id: int,
    conversation_id: int | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """把一次请求的 token 消耗写入 token_usage 表。"""
    db.add(
        TokenUsage(
            user_id=user_id,
            conversation_id=conversation_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
    )
    db.commit()


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """按参考价格表估算单次成本（美元）；开关关闭或模型未知时返回 None。"""
    if not settings.TOKEN_USAGE_COST_ENABLED:
        return None
    price = _MODEL_PRICES_PER_1M.get(model)
    if price is None:
        return None
    in_price, out_price = price
    cost = prompt_tokens / 1_000_000 * in_price + completion_tokens / 1_000_000 * out_price
    return round(cost, 6)


def get_usage_summary(db: Session, user_id: int, days: int = 30) -> dict:
    """聚合当前用户最近 days 天的用量：总计、按模型、按天。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    scope = (
        TokenUsage.user_id == user_id,
        TokenUsage.created_at >= since,
    )

    total_row = (
        db.query(
            func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
            func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
            func.coalesce(func.sum(TokenUsage.total_tokens), 0),
            func.count(TokenUsage.id),
        )
        .filter(*scope)
        .one()
    )
    total_prompt, total_completion, total_tokens, request_count = total_row

    model_rows = (
        db.query(
            TokenUsage.model,
            func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
            func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
            func.coalesce(func.sum(TokenUsage.total_tokens), 0),
        )
        .filter(*scope)
        .group_by(TokenUsage.model)
        .order_by(func.sum(TokenUsage.total_tokens).desc())
        .all()
    )
    by_model = [
        {
            "model": model,
            "prompt_tokens": p,
            "completion_tokens": c,
            "total_tokens": t,
            "cost_usd": estimate_cost_usd(model, p, c),
        }
        for model, p, c, t in model_rows
    ]
    est_cost = (
        round(sum(m["cost_usd"] or 0 for m in by_model), 6) if by_model else None
    )

    # 按天聚合放 Python 侧做，SQLite / PostgreSQL 都能跑（不依赖 date_trunc）
    day_rows = (
        db.query(TokenUsage.created_at, TokenUsage.total_tokens)
        .filter(*scope)
        .all()
    )
    per_day: dict[str, int] = {}
    for created_at, total in day_rows:
        day = created_at.strftime("%Y-%m-%d") if created_at else "unknown"
        per_day[day] = per_day.get(day, 0) + (total or 0)

    return {
        "window_days": days,
        "request_count": request_count,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "total_cost_usd": est_cost,
        "by_model": by_model,
        "by_day": [
            {"day": day, "total_tokens": tokens}
            for day, tokens in sorted(per_day.items())
        ],
    }
