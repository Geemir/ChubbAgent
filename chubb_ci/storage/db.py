"""Database engine, schema creation, and session helpers.

SQLite by default; swap to PostgreSQL by setting ``CHUBB_DB_URL`` — no code change
(the ORM is SQLModel/SQLAlchemy).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from loguru import logger
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

from chubb_ci.config.settings import Settings

# Import models so SQLModel.metadata is fully populated before create_all.
import chubb_ci.schemas.models  # noqa: F401

_engine: Engine | None = None


def get_engine(settings: Settings, echo: bool = False) -> Engine:
    """Return a process-wide engine for the configured database URL."""
    global _engine
    if _engine is None:
        url = settings.database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        if url.startswith("sqlite"):
            settings.ensure_dirs()
        _engine = create_engine(url, echo=echo, connect_args=connect_args)
        logger.debug("DB engine created for {}", url)
    return _engine


def init_db(settings: Settings) -> Engine:
    """Create all tables (idempotent)."""
    engine = get_engine(settings)
    SQLModel.metadata.create_all(engine)
    logger.info("Database initialized at {}", settings.database_url)
    return engine


@contextmanager
def session_scope(settings: Settings) -> Iterator[Session]:
    """Transactional session context: commit on success, rollback on error."""
    engine = get_engine(settings)
    # expire_on_commit=False so returned rows keep their loaded column values after
    # the session closes (callers/exporters read them post-commit).
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _reset_engine_for_tests() -> None:
    """Test hook: drop the cached engine so a new URL can be used."""
    global _engine
    _engine = None
