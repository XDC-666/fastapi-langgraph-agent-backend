"""应用配置：从环境变量或 .env 读取，pydantic-settings 统一管理与校验。"""
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
    # 允许跨域的前端源（逗号分隔），生产环境务必改为实际前端域名
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ===== 安全 =====
    SECRET_KEY: str = "change-me-to-a-random-secret-string"
    # 设为 true 时，SECRET_KEY 仍为默认占位值则启动报错（防生产用弱密钥）
    REQUIRE_SECRET_KEY: bool = False
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    # ===== 数据库 =====
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/agentdb"
    # 开发环境用 create_all 省事；生产设为 false 改用 Alembic 迁移
    # （create_all 不会 ALTER 已有表，改表结构时会字段不一致）
    AUTO_CREATE_TABLES: bool = True

    # ===== Redis =====
    REDIS_URL: str = "redis://localhost:6379/0"

    # ===== 大模型 API =====
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"

    # ===== 对话 / Checkpointer =====
    # 每次请求携带的历史消息条数上限（防长对话 token 超限）
    MAX_HISTORY_MESSAGES: int = 20
    # 留空用内存版 MemorySaver（重启即失）；设 sqlite:///... 可持久化，
    # 需额外安装 langgraph-checkpoint-sqlite
    CHECKPOINTER_URI: str = ""

    # ===== Token 用量统计 =====
    # /usage 接口是否给已知模型估算成本（美元）
    TOKEN_USAGE_COST_ENABLED: bool = True

    # ===== 登录失败锁定 =====
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    LOGIN_LOCKOUT_WINDOW_MINUTES: int = 15

    # ===== 限流（基于 Redis，不可用时降级放行）=====
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 10  # 登录按 IP，防爆破
    RATE_LIMIT_CHAT_PER_MINUTE: int = 30   # 对话按用户，防 token 成本失控
    # 部署在可信反向代理之后时设为 True（取 X-Forwarded-For 原始客户端 IP）；
    # 默认 False，忽略该头以防伪造绕过限流
    TRUST_PROXY: bool = False

    # ===== 嵌入模型 =====
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # ===== 知识库 =====
    MAX_KNOWLEDGE_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 单文件上限 10 MiB
    MAX_KNOWLEDGE_K: int = 10  # 相似度检索结果上限

    # ===== 本地数据目录 =====
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    UPLOAD_DIR: str = "./data/uploads"


@lru_cache
def get_settings() -> Settings:
    """返回全局单例配置。"""
    s = Settings()
    if s.REQUIRE_SECRET_KEY and s.SECRET_KEY == "change-me-to-a-random-secret-string":
        raise ValueError(
            "REQUIRE_SECRET_KEY=true 但 SECRET_KEY 仍为默认占位值，"
            "请在环境变量 / .env 中设置一个随机强密钥"
        )
    return s


settings = get_settings()
