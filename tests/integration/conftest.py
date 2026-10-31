"""Integration fixtures: a throwaway `<db>_test` database, built by running the real migrations."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from medagent.core.config import get_settings


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    base_url = make_url(get_settings().database_url)
    test_db = f"{base_url.database}_test"
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    except Exception as exc:  # DB not reachable: tell the developer what to do
        pytest.skip(f"Postgres unavailable ({type(exc).__name__}); run `docker compose up -d`")

    test_url = base_url.set(database=test_db).render_as_string(hide_password=False)
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", test_url)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")  # exercises the migrations themselves
    eng = create_engine(test_url)
    yield eng
    eng.dispose()
    mp.undo()
    get_settings.cache_clear()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE kb_chunks, kb_documents, appointments, doctor_schedules, "
                "patients, doctors "
                "RESTART IDENTITY CASCADE"
            )
        )
    with Session(engine, expire_on_commit=False) as s:
        yield s
