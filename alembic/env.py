"""Alembic 运行环境。

关键点：
- 连接串从 app.config.settings.DATABASE_URL 读取（与项目其余部分共用同一份配置）。
- target_metadata 指向 app.database.Base.metadata，autogenerate 才能对比出模型变更。
- 必须 import 所有模型（app.models），否则 metadata 里缺少对应表。
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base
from app.models import Conversation, Message, TokenUsage, User  # noqa: F401 注册全部模型（仅副作用）

# Alembic 自带的 Config 对象
config = context.config

# 用项目配置覆盖 sqlalchemy.url，避免在两处重复维护连接串
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不真正连接数据库（用于 review / CI 产出迁移脚本）。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：真正连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
