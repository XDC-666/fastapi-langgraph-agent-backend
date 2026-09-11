"""Token 用量统计服务。

为什么需要它：AI 后端的成本 = token 消耗。记录每次对话的 prompt / completion token，
既能做成本意识（面试加分），也能发现异常刷量。

token 数来源：LangChain 在 LLM 返回里会带上 usage_metadata。
Agent 调用工具时一轮请求可能触发多次 LLM 调用，因此这里累计每次调用的 usage；
不同版本字段名可能是 prompt_tokens/completion_tokens 或 input_tokens/output_tokens，
这里统一兼容。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.usage import TokenUsage

# 已知模型的参考价格（美元 / 1M tokens），仅用于估算，非实时报价。
# 顺序：(输入单价, 输出单价)
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
    """合并两段 token usage，用于聚合一轮 Agent 内的多次模型调用。"""
    if new is None:
        return current
    if current is None:
        return new
    return (
        current[0] + new[0],
        current[1] + new[1],
        current[2] + new[2],
    )


def extract_token_usage(*messages) -> tuple[int, int, int] | None:
    """聚合若干 LangChain 消息上的 token 用量。

    Agent 可能因工具调用在一轮请求里多次调用 LLM，因此不能只取最后一条
    AIMessage。返回整轮累计的 (prompt_tokens, completion_tokens, total_tokens)；
    所有消息都没有 usage_metadata 时返回 None。
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
    row = TokenUsage(
        user_id=user_id,
        conversation_id=conversation_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    db.add(row)
    db.commit()


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """估算某次请求成本（美元）；未知模型返回 None。"""
    if not settings.TOKEN_USAGE_COST_ENABLED:
        return None
    price = _MODEL_PRICES_PER_1M.get(model)
    if price is None:
        return None
    in_price, out_price = price
    cost = prompt_tokens / 1_000_000 * in_price + completion_tokens / 1_000_000 * out_price
    return round(cost, 6)


def get_usage_summary(db: Session, user_id: int, days: int = 30) -> dict:
    """聚合当前用户的用量统计。

    返回：总 token、按模型拆分、按天拆分（最近 days 天）。
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total_row = (
        db.query(
            func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
            func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
            func.coalesce(func.sum(TokenUsage.total_tokens), 0),
            func.count(TokenUsage.id),
        )
        .filter(TokenUsage.user_id == user_id, TokenUsage.created_at >= since)
        .one()
    )
    total_prompt, total_completion, total_tokens, request_count = total_row

    by_model = (
        db.query(
            TokenUsage.model,
            func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
            func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
            func.coalesce(func.sum(TokenUsage.total_tokens), 0),
        )
        .filter(TokenUsage.user_id == user_id, TokenUsage.created_at >= since)
        .group_by(TokenUsage.model)
        .order_by(func.sum(TokenUsage.total_tokens).desc())
        .all()
    )

    # 按天聚合在 Python 侧完成，避免依赖 PostgreSQL 专属的 date_trunc
    # （这样同一份逻辑在 SQLite / PostgreSQL 上都能跑，测试与生产一致）
    day_rows = (
        db.query(TokenUsage.created_at, TokenUsage.total_tokens)
        .filter(TokenUsage.user_id == user_id, TokenUsage.created_at >= since)
        .all()
    )
    by_day_map: dict[str, int] = {}
    for created_at, total in day_rows:
        day_str = created_at.strftime("%Y-%m-%d") if created_at else "unknown"
        by_day_map[day_str] = by_day_map.get(day_str, 0) + (total or 0)
    by_day = [{"day": d, "total_tokens": t} for d, t in sorted(by_day_map.items())]

    by_model_out = []
    for model, p, c, t in by_model:
        by_model_out.append(
            {
                "model": model,
                "prompt_tokens": p,
                "completion_tokens": c,
                "total_tokens": t,
                # 按模型估算整体成本（已知模型才有值）
                "cost_usd": estimate_cost_usd(model, p, c),
            }
        )

    est_cost = None
    if by_model_out:
        est_cost = round(sum(r["cost_usd"] or 0 for r in by_model_out), 6)

    return {
        "window_days": days,
        "request_count": request_count,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "total_cost_usd": est_cost,
        "by_model": by_model_out,
        "by_day": by_day,
    }
