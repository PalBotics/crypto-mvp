"""Shared fixtures for integration tests.

Uses an in-memory SQLite database so integration tests run without a live
PostgreSQL instance. Three SQLite compatibility patches are applied at import
time:

    - postgresql.UUID(as_uuid=True) -> CHAR(32)
      SQLAlchemy's bind/result processors handle UUID <-> hex-string conversion.

    - postgresql.JSONB -> JSON
      SQLite stores JSON as TEXT; SQLAlchemy's JSON processors handle
      serialisation/deserialisation transparently.

    - SQLiteDATETIME result_processor -> always returns UTC-aware datetimes
      SQLite stores datetimes as naive strings; SQLAlchemy 2.x merges DB row
      values back into identity-map objects on every SELECT, so without this
      patch any DateTime(timezone=True) column becomes timezone-naive after the
      first read-back, breaking ensure_utc() in domain contracts.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import DATETIME as SQLiteDATETIME
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


# Patch SQLite DATETIME result processor to always return UTC-aware datetimes.
# SQLite strips timezone info on storage; SQLAlchemy 2.x re-applies DB row
# values into the identity map on every SELECT, so we must add UTC back here.
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

import core.models  # noqa: F401, E402  (registers all mappers with Base.metadata)

from core.db.base import Base  # noqa: E402


# ------------------------------------------------------------------
# Session fixture
# ------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session() -> Session:
    """Yield a SQLAlchemy Session backed by a fresh in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:", echo=False)
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
