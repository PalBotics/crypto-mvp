"""Integration tests for the dashboard HTTP API.

Uses FastAPI TestClient with the db_session fixture from conftest.py.
The session dependency is overridden so routes hit the same in-memory
SQLite database used to seed test data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from apps.dashboard.main import app
from apps.dashboard.routes import get_session
from core.models.fill_record import FillRecord
from core.models.funding_payment import FundingPayment
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent

ACCOUNT = "test_run_abc"
OTHER = "other_run_xyz"
NOW = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Session override — routes use db_session fixture instead of real DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(db_session):
    """Return a TestClient with the DB session dependency overridden."""

    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers (minimal records only)
# ---------------------------------------------------------------------------


def _add_position(session, account_name, symbol, quantity, avg_entry_price=Decimal("100")):
    pos = PositionSnapshot(
        id=uuid.uuid4(),
        exchange="test",
        symbol=symbol,
        account_name=account_name,
        instrument_type="spot",
        side="long",
        quantity=quantity,
        avg_entry_price=avg_entry_price,
        snapshot_ts=NOW,
    )
    session.add(pos)
    return pos


def _add_pnl(session, account_name, realized, unrealized):
    snap = PnLSnapshot(
        id=uuid.uuid4(),
        strategy_name=account_name,
        symbol="BTC",
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=realized + unrealized,
        net_pnl=realized + unrealized,
        snapshot_ts=NOW,
    )
    session.add(snap)
    return snap


def _add_funding(session, account_name, amount):
    fp = FundingPayment(
        id=uuid.uuid4(),
        exchange="test",
        symbol="BTC-PERP",
        account_name=account_name,
        position_quantity=Decimal("1"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
        payment_amount=amount,
        accrued_ts=NOW,
        created_ts=NOW,
    )
    session.add(fp)
    return fp


def _add_fill_chain(session, account_name, fill_price=Decimal("100"), fill_qty=Decimal("1"), fee=Decimal("0.05")):
    intent = OrderIntent(
        id=uuid.uuid4(),
        mode=account_name,
        exchange="test",
        symbol="BTC",
        side="buy",
        order_type="market",
        quantity=fill_qty,
        reduce_only=False,
        post_only=False,
        status="filled",
        created_ts=NOW,
    )
    orec = OrderRecord(
        id=uuid.uuid4(),
        order_intent_id=intent.id,
        exchange="test",
        symbol="BTC",
        exchange_order_id=str(uuid.uuid4()),
        side="buy",
        order_type="market",
        status="filled",
        submitted_qty=fill_qty,
        filled_qty=fill_qty,
        avg_fill_price=fill_price,
        fees_paid=fee,
        raw_exchange_payload={},
        created_ts=NOW,
        updated_ts=NOW,
    )
    fill = FillRecord(
        id=uuid.uuid4(),
        order_record_id=orec.id,
        exchange="test",
        symbol="BTC",
        side="buy",
        fill_price=fill_price,
        fill_qty=fill_qty,
        fill_notional=fill_price * fill_qty,
        fee_paid=fee,
        fill_ts=NOW,
        ingested_ts=NOW,
    )
    session.add(intent)
    session.add(orec)
    session.add(fill)
    return intent, orec, fill


def _add_risk_event(session, account_name, severity="warn"):
    ev = RiskEvent(
        id=uuid.uuid4(),
        event_type="limit_breached",
        severity=severity,
        strategy_name=account_name,
        rule_name="max_notional",
        details_json={"threshold": 1000, "actual": 1500},
        created_ts=NOW,
    )
    session.add(ev)
    return ev


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_returns_200_and_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /runs/{account_name}/summary
# ---------------------------------------------------------------------------


class TestRunSummary:
    def test_returns_200_with_zero_data(self, client):
        resp = client.get(f"/runs/{ACCOUNT}/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["account_name"] == ACCOUNT
        assert body["open_position_count"] == 0
        assert body["total_fills"] == 0
        assert body["total_risk_events"] == 0
        assert body["realized_pnl"] == "0"
        assert body["net_pnl"] == "0"

    def test_returns_correct_counts_and_decimals(self, client, db_session):
        _add_position(db_session, ACCOUNT, "BTC", Decimal("1"))
        _add_pnl(db_session, ACCOUNT, Decimal("50"), Decimal("10"))
        _add_funding(db_session, ACCOUNT, Decimal("-3"))
        _add_fill_chain(db_session, ACCOUNT)
        _add_risk_event(db_session, ACCOUNT)
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["account_name"] == ACCOUNT
        assert body["open_position_count"] == 1
        assert body["total_fills"] == 1
        assert body["total_risk_events"] == 1
        assert Decimal(body["realized_pnl"]) == Decimal("50")
        assert Decimal(body["unrealized_pnl"]) == Decimal("10")
        assert Decimal(body["funding_paid"]) == Decimal("-3")
        assert Decimal(body["net_pnl"]) == Decimal("57")  # 50 + 10 - 3

    def test_decimal_fields_are_strings(self, client):
        resp = client.get(f"/runs/{ACCOUNT}/summary")
        body = resp.json()
        assert isinstance(body["realized_pnl"], str)
        assert isinstance(body["net_pnl"], str)

    def test_other_account_does_not_bleed_through(self, client, db_session):
        _add_pnl(db_session, OTHER, Decimal("999"), Decimal("999"))
        _add_fill_chain(db_session, OTHER)
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/summary")
        body = resp.json()
        assert body["total_fills"] == 0
        assert body["realized_pnl"] == "0"


# ---------------------------------------------------------------------------
# /runs/{account_name}/positions
# ---------------------------------------------------------------------------


class TestPositions:
    def test_returns_200_with_empty_list(self, client):
        resp = client.get(f"/runs/{ACCOUNT}/positions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_open_positions(self, client, db_session):
        _add_position(db_session, ACCOUNT, "BTC", Decimal("2"), avg_entry_price=Decimal("48000"))
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/positions")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["symbol"] == "BTC"
        assert body[0]["account_name"] == ACCOUNT
        assert Decimal(body[0]["quantity"]) == Decimal("2")
        assert Decimal(body[0]["avg_entry_price"]) == Decimal("48000")

    def test_excludes_zero_quantity(self, client, db_session):
        _add_position(db_session, ACCOUNT, "ETH", Decimal("0"))
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/positions")
        assert resp.json() == []

    def test_excludes_other_account(self, client, db_session):
        _add_position(db_session, OTHER, "BTC", Decimal("5"))
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/positions")
        assert resp.json() == []

    def test_quantity_is_string(self, client, db_session):
        _add_position(db_session, ACCOUNT, "BTC", Decimal("1"))
        db_session.commit()

        body = client.get(f"/runs/{ACCOUNT}/positions").json()
        assert isinstance(body[0]["quantity"], str)
        assert isinstance(body[0]["avg_entry_price"], str)


# ---------------------------------------------------------------------------
# /runs/{account_name}/pnl
# ---------------------------------------------------------------------------


class TestPnL:
    def test_returns_200_with_zero_data(self, client):
        resp = client.get(f"/runs/{ACCOUNT}/pnl")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_realized_pnl"] == "0"
        assert body["total_unrealized_pnl"] == "0"
        assert body["total_funding_paid"] == "0"
        assert body["net_pnl"] == "0"

    def test_returns_aggregated_pnl(self, client, db_session):
        _add_pnl(db_session, ACCOUNT, Decimal("100"), Decimal("20"))
        _add_pnl(db_session, ACCOUNT, Decimal("50"), Decimal("5"))
        _add_funding(db_session, ACCOUNT, Decimal("-8"))
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/pnl")
        body = resp.json()
        assert Decimal(body["total_realized_pnl"]) == Decimal("150")
        assert Decimal(body["total_unrealized_pnl"]) == Decimal("25")
        assert Decimal(body["total_funding_paid"]) == Decimal("-8")
        assert Decimal(body["net_pnl"]) == Decimal("167")  # 150 + 25 - 8

    def test_excludes_other_account(self, client, db_session):
        _add_pnl(db_session, OTHER, Decimal("999"), Decimal("0"))
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/pnl")
        body = resp.json()
        assert body["total_realized_pnl"] == "0"

    def test_decimal_fields_are_strings(self, client):
        body = client.get(f"/runs/{ACCOUNT}/pnl").json()
        assert isinstance(body["total_realized_pnl"], str)
        assert isinstance(body["net_pnl"], str)


# ---------------------------------------------------------------------------
# /runs/{account_name}/fills
# ---------------------------------------------------------------------------


class TestFills:
    def test_returns_200_with_empty_list(self, client):
        resp = client.get(f"/runs/{ACCOUNT}/fills")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_fill_data(self, client, db_session):
        _add_fill_chain(db_session, ACCOUNT, fill_price=Decimal("50000"), fee=Decimal("1.5"))
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/fills")
        body = resp.json()
        assert len(body) == 1
        assert body[0]["symbol"] == "BTC"
        assert body[0]["side"] == "buy"
        assert Decimal(body[0]["fill_price"]) == Decimal("50000")
        assert Decimal(body[0]["fee_amount"]) == Decimal("1.5")

    def test_excludes_other_account(self, client, db_session):
        _add_fill_chain(db_session, OTHER)
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/fills")
        assert resp.json() == []

    def test_respects_limit_param(self, client, db_session):
        for _ in range(10):
            _add_fill_chain(db_session, ACCOUNT)
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/fills?limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_limit_max_is_500(self, client):
        resp = client.get(f"/runs/{ACCOUNT}/fills?limit=501")
        assert resp.status_code == 422

    def test_fill_price_is_string(self, client, db_session):
        _add_fill_chain(db_session, ACCOUNT)
        db_session.commit()

        body = client.get(f"/runs/{ACCOUNT}/fills").json()
        assert isinstance(body[0]["fill_price"], str)
        assert isinstance(body[0]["fill_qty"], str)
        assert isinstance(body[0]["fee_amount"], str)


# ---------------------------------------------------------------------------
# /runs/{account_name}/risk-events
# ---------------------------------------------------------------------------


class TestRiskEvents:
    def test_returns_200_with_empty_list(self, client):
        resp = client.get(f"/runs/{ACCOUNT}/risk-events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_risk_event_data(self, client, db_session):
        _add_risk_event(db_session, ACCOUNT, severity="critical")
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/risk-events")
        body = resp.json()
        assert len(body) == 1
        assert body[0]["rule_name"] == "max_notional"
        assert body[0]["event_type"] == "limit_breached"
        assert body[0]["severity"] == "critical"
        assert isinstance(body[0]["details"], dict)
        assert body[0]["details"]["threshold"] == 1000

    def test_excludes_other_account(self, client, db_session):
        _add_risk_event(db_session, OTHER)
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/risk-events")
        assert resp.json() == []

    def test_respects_limit_param(self, client, db_session):
        for _ in range(10):
            _add_risk_event(db_session, ACCOUNT)
        db_session.commit()

        resp = client.get(f"/runs/{ACCOUNT}/risk-events?limit=4")
        assert resp.status_code == 200
        assert len(resp.json()) == 4

    def test_limit_max_is_200(self, client):
        resp = client.get(f"/runs/{ACCOUNT}/risk-events?limit=201")
        assert resp.status_code == 422
