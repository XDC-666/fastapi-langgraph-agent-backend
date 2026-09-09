"""应用配置：从环境变量或 .env 文件读取。

使用 pydantic-settings，所有配置集中在一处，方便管理与类型校验。
"""
import logging
import secrets

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ===== 应用 =====
    PROJECT_NAME: str = "fastapi-langgraph-agent-backend"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # 允许跨域的前端源（逗号分隔）；生产环境务必改为你的前端域名
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ===== 安全 =====
    SECRET_KEY: str = "change-me-to-a-random-secret-string"
    # 设为 true 时，若 SECRET_KEY 仍为默认占位值则启动报错（防止生产用弱密钥）
    REQUIRE_SECRET_KEY: bool = False
    # 是否信任反向代理的 X-Forwarded-For 以获取真实客户端 IP。
    # 仅当确有可信代理（如 Nginx）在前时才设 true；否则攻击者可用伪造的
    # X-Forwarded-For 绕过基于 IP 的限流。
    TRUST_PROXY: bool = False
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    # ===== 数据库 =====
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/agentdb"

    # 启动是否自动建表。开发/测试环境设为 true 用 create_all 最省事；
    # 生产环境请设为 false，并改用 Alembic 迁移（alembic upgrade head），
    # 否则改表结构时 create_all 不会去 ALTER 已有表，易引发字段不一致。
    AUTO_CREATE_TABLES: bool = True

    # ===== Redis =====
    REDIS_URL: str = "redis://localhost:6379/0"

    # ===== 大模型 API =====
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"

    # ===== 对话 =====
    # 每次请求携带的历史消息条数上限（防止长对话导致 token 超限 / 成本失控）
    MAX_HISTORY_MESSAGES: int = 20

    # ===== LangGraph Checkpointer =====
    # 留空：使用内存版 MemorySaver（随进程重启丢失，适合开发 / 单实例演示）。
    # 设为 sqlite:///./data/checkpoints.sqlite 可持久化 Agent 工作记忆（跨重启可恢复），
    # 需要先额外安装：pip install langgraph-checkpoint-sqlite
    CHECKPOINTER_URI: str = ""

    # ===== Token 用量统计 =====
    # 是否在 /usage 接口给已知模型估算成本（美元）。未知模型返回 null。
    TOKEN_USAGE_COST_ENABLED: bool = True

    # ===== 登录失败锁定 =====
    # 同一账号（按登录标识）在窗口内失败达到上限即锁定；Redis 不可用时自动降级（不锁定）。
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    LOGIN_LOCKOUT_WINDOW_MINUTES: int = 15

    # ===== 限流（基于 Redis；Redis 不可用时自动降级放行）=====
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 10  # 登录按 IP，防暴力破解
    RATE_LIMIT_CHAT_PER_MINUTE: int = 30  # 对话按用户，防刷接口导致 token 成本失控

    # ===== 嵌入模型 =====
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # ===== 本地数据目录 =====
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    UPLOAD_DIR: str = "./data/uploads"


logger = logging.getLogger(__name__)


@lru_cache
def get_settings() -> Settings:
    """返回全局单例配置。"""
    s = Settings()
    # 生产环境强制要求自定义 SECRET_KEY，避免 JWT 被已知默认密钥伪造
    if s.REQUIRE_SECRET_KEY and s.SECRET_KEY == "change-me-to-a-random-secret-string":
        raise ValueError(
            "REQUIRE_SECRET_KEY=true 但 SECRET_KEY 仍为默认占位值，"
            "请在环境变量 / .env 中设置一个随机强密钥"
        )
    # 兜底：任何环境（含生产）若仍使用可预测的默认占位密钥，立即替换为本次进程
    # 专用的随机密钥，杜绝「忘记设置 → JWT 被已知字符串伪造」的风险。
    # 注意：随机密钥仅在进程内有效，重启后旧 token 失效；因此生产仍应通过
    # 环境变量设置固定强密钥，并将 REQUIRE_SECRET_KEY 设为 true。
    if s.SECRET_KEY == "change-me-to-a-random-secret-string":
        s.SECRET_KEY = secrets.token_urlsafe(32)
        logger.warning(
            "未显式设置 SECRET_KEY，已生成本次进程专用临时随机密钥（重启后失效）。"
            "生产环境请通过环境变量设置固定强密钥，并将 REQUIRE_SECRET_KEY 设为 true。"
        )
    return s


settings = get_settings()
