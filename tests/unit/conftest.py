"""Shared fixtures for unit tests that need a database session.

Uses an in-memory SQLite database with the same compatibility patches as the
integration test conftest so that PostgreSQL-specific column types (UUID, JSONB,
timezone-aware DateTime) work correctly under SQLite.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import DATETIME as SQLiteDATETIME
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import Session, sessionmaker

# ------------------------------------------------------------------
# SQLite type compatibility patches (applied once at import time)
# ------------------------------------------------------------------


def _visit_JSONB(self, type_, **kw):  # noqa: N802
    return "JSON"


def _visit_UUID(self, type_, **kw):  # noqa: N802
    return "CHAR(32)"


SQLiteTypeCompiler.visit_JSONB = _visit_JSONB
SQLiteTypeCompiler.visit_UUID = _visit_UUID

_orig_datetime_result_processor = SQLiteDATETIME.result_processor


def _utc_datetime_result_processor(self, dialect, coltype):  # noqa: N802
    process = _orig_datetime_result_processor(self, dialect, coltype)

    if process is None:
        def _add_utc(value):
            if value is not None and isinstance(value, datetime) and value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        return _add_utc

    def _wrap(value):
        result = process(value)
        if result is not None and isinstance(result, datetime) and result.tzinfo is None:
            return result.replace(tzinfo=timezone.utc)
        return result

    return _wrap


SQLiteDATETIME.result_processor = _utc_datetime_result_processor

# ------------------------------------------------------------------
# Model registration — must happen after patches, before create_all
# ------------------------------------------------------------------

import core.models  # noqa: F401, E402

from core.db.base import Base  # noqa: E402

# ------------------------------------------------------------------
# Session fixture
# ------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_session() -> Session:
    """Yield a SQLAlchemy Session backed by a fresh in-memory SQLite database."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    SessionFactory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
