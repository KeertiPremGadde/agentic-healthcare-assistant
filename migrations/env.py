"""Alembic environment: URL from medagent settings, metadata from the ORM models."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from medagent.core.config import get_settings
from medagent.db import models  # noqa: F401  (registers all tables on Base.metadata)
from medagent.db.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata

# Tables owned by other libraries (ADR 0006): LangGraph's PostgresSaver creates and migrates
# `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` itself.
# Without this filter, autogenerate would propose dropping them (and every conversation).
EXTERNALLY_MANAGED_PREFIXES = ("checkpoint",)


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    if type_ == "table" and name is not None:
        return not name.startswith(EXTERNALLY_MANAGED_PREFIXES)
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_name=include_name
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
