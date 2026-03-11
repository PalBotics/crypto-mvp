"""Tests for the Paper Deposits feature.

Covers:
- deposit creates record correctly
- negative / zero / over-limit amounts rejected
- account value includes total deposited
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from apps.dashboard.main import app
from apps.dashboard.routes import get_session
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.paper_deposit import PaperDeposit
from core.reporting.account import compute_paper_account_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _book(session, ts: datetime) -> None:
    session.add(
        OrderBookSnapshot(
            exchange="kraken",
            adapter_name="kraken_rest",
            symbol="XBTUSD",
            exchange_symbol="XXBTZUSD",
            bid_price_1=Decimal("70490"),
            bid_size_1=Decimal("1"),
            ask_price_1=Decimal("70510"),
            ask_size_1=Decimal("1"),
            bid_price_2=None,
            bid_size_2=None,
            ask_price_2=None,
            ask_size_2=None,
            bid_price_3=None,
            bid_size_3=None,
            ask_price_3=None,
            ask_size_3=None,
            spread=Decimal("20"),
            spread_bps=Decimal("2.84"),
            mid_price=Decimal("70500"),
            event_ts=ts,
            ingested_ts=ts,
        )
    )


@pytest.fixture()
def client(db_session):
    """TestClient with the DB session dependency overridden."""
    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_deposit_creates_record(db_session) -> None:
    now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    deposit = PaperDeposit(
        id=uuid.uuid4(),
        amount=Decimal("500.00"),
        note="Test deposit",
        created_ts=now,
    )
    db_session.add(deposit)
    db_session.commit()

    retrieved = db_session.execute(select(PaperDeposit)).scalars().first()
    assert retrieved is not None
    assert Decimal(str(retrieved.amount)) == Decimal("500.00")
    assert retrieved.note == "Test deposit"
    assert retrieved.created_ts is not None


def test_account_value_includes_deposits(db_session) -> None:
    now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    _book(db_session, now)

    deposit = PaperDeposit(
        id=uuid.uuid4(),
        amount=Decimal("500.00"),
        note=None,
        created_ts=now,
    )
    db_session.add(deposit)
    db_session.commit()

    snapshot = compute_paper_account_snapshot(
        session=db_session,
        account_name="paper_mm",
        exchange="kraken",
        symbol="XBTUSD",
        starting_capital=Decimal("1000.00"),
    )

    assert snapshot.total_deposited == Decimal("500.00")
    assert snapshot.deposit_count == 1
    # effective_capital = 1000 + 500 = 1500; no pnl, fees, or unrealized
    assert snapshot.account_value == Decimal("1500.00")


def test_negative_deposit_amount_rejected(client) -> None:
    resp = client.post("/api/deposit", json={"amount": "-100"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "positive" in detail


def test_zero_deposit_amount_rejected(client) -> None:
    resp = client.post("/api/deposit", json={"amount": "0"})
    assert resp.status_code == 422


def test_overlimit_deposit_amount_rejected(client) -> None:
    resp = client.post("/api/deposit", json={"amount": "10001"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "10000" in detail
