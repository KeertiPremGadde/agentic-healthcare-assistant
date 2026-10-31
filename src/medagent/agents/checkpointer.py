"""Postgres checkpointer: the graph's memory, persisted per thread_id.

LangGraph's `setup()` creates and migrates its own tables (`checkpoints`, `checkpoint_blobs`,
`checkpoint_writes`, `checkpoint_migrations`). They are owned by the library, not by our Alembic
migrations (ADR 0006). `setup()` is idempotent, so calling it on every start is safe.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver

from medagent.core.config import get_settings


def psycopg_url(sqlalchemy_url: str) -> str:
    """`postgresql+psycopg://...` (SQLAlchemy) -> `postgresql://...` (plain psycopg)."""
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def postgres_checkpointer(database_url: str | None = None) -> Iterator[PostgresSaver]:
    url = psycopg_url(database_url or get_settings().database_url)
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()
        yield saver
