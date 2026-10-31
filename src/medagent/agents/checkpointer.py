"""Postgres checkpointer: the graph's memory, persisted per thread_id.

LangGraph's `setup()` creates and migrates its own tables (`checkpoints`, `checkpoint_blobs`,
`checkpoint_writes`, `checkpoint_migrations`). They are owned by the library, not by our Alembic
migrations (ADR 0006). `setup()` is idempotent, so calling it on every start is safe.

The async saver uses psycopg's async mode, which on Windows needs a SelectorEventLoop
(`medagent.core.aio.run` takes care of that).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from medagent.core.config import get_settings


def psycopg_url(sqlalchemy_url: str) -> str:
    """`postgresql+psycopg://...` (SQLAlchemy) -> `postgresql://...` (plain psycopg)."""
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


@asynccontextmanager
async def postgres_checkpointer(
    database_url: str | None = None,
) -> AsyncIterator[AsyncPostgresSaver]:
    url = psycopg_url(database_url or get_settings().database_url)
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
        yield saver


@asynccontextmanager
async def postgres_checkpointer_pool(
    database_url: str | None = None, max_size: int = 10
) -> AsyncIterator[AsyncPostgresSaver]:
    """A checkpointer on a connection pool, for the API (concurrent conversations). The single
    connection used by `postgres_checkpointer` would serialise every request."""
    url = psycopg_url(database_url or get_settings().database_url)
    pool = AsyncConnectionPool(
        url,
        max_size=max_size,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
        yield saver
    finally:
        await pool.close()
