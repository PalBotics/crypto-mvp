"""Unit tests for core/reporting/queries.py.

Seeds minimal records directly against an in-memory SQLite database and
verifies each query function independently. Each test class covers one
query function. Cross-account isolation is verified in every test class.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.models.fill_record import FillRecord
from core.models.funding_payment import FundingPayment
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent
from core.reporting.queries import (
    FillRow,
    PnLSummaryRow,
    PositionRow,
    RiskEventRow,
    RunSummaryRow,
    get_open_positions,
    get_pnl_summary,
    get_recent_fills,
    get_risk_events,
    get_run_summary,
)

ACCOUNT = "test_account"
OTHER = "other_account"
NOW = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _position(
    account_name: str,
    symbol: str,
    quantity: Decimal,
    avg_entry_price: Decimal = Decimal("100"),
) -> PositionSnapshot:
    return PositionSnapshot(
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


def _pnl(
    account_name: str,
    realized: Decimal,
    unrealized: Decimal,
    symbol: str = "BTC",
) -> PnLSnapshot:
    return PnLSnapshot(
        id=uuid.uuid4(),
        strategy_name=account_name,
        symbol=symbol,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=realized + unrealized,
        net_pnl=realized + unrealized,
        snapshot_ts=NOW,
    )


def _funding(account_name: str, amount: Decimal) -> FundingPayment:
    return FundingPayment(
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


def _fill_chain(
    account_name: str,
    fill_price: Decimal = Decimal("100"),
    fill_qty: Decimal = Decimal("1"),
    fee: Decimal = Decimal("0.05"),
    symbol: str = "BTC",
) -> tuple[OrderIntent, OrderRecord, FillRecord]:
    """Return an (OrderIntent, OrderRecord, FillRecord) triple sharing the same run."""
    intent = OrderIntent(
        id=uuid.uuid4(),
        mode=account_name,
        exchange="test",
        symbol=symbol,
        side="buy",
        order_type="market",
        quantity=fill_qty,
        reduce_only=False,
        post_only=False,
        status="filled",
        created_ts=NOW,
    )
    order_rec = OrderRecord(
        id=uuid.uuid4(),
        order_intent_id=intent.id,
        exchange="test",
        symbol=symbol,
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
        order_record_id=order_rec.id,
        exchange="test",
        symbol=symbol,
        side="buy",
        fill_price=fill_price,
        fill_qty=fill_qty,
        fill_notional=fill_price * fill_qty,
        fee_paid=fee,
        fill_ts=NOW,
        ingested_ts=NOW,
    )
    return intent, order_rec, fill


def _risk_event(account_name: str, severity: str = "warn") -> RiskEvent:
    return RiskEvent(
        id=uuid.uuid4(),
        event_type="limit_breached",
        severity=severity,
        strategy_name=account_name,
        rule_name="max_notional",
        details_json={"threshold": 1000, "actual": 1500},
        created_ts=NOW,
    )


# ---------------------------------------------------------------------------
# get_open_positions
# ---------------------------------------------------------------------------


class TestGetOpenPositions:
    def test_returns_row_for_positive_quantity(self, db_session):
        db_session.add(_position(ACCOUNT, "BTC", Decimal("1.5")))
        db_session.commit()

        result = get_open_positions(db_session, ACCOUNT)

        assert len(result) == 1
        assert isinstance(result[0], PositionRow)
        assert result[0].symbol == "BTC"
        assert result[0].account_name == ACCOUNT
        assert result[0].quantity == Decimal("1.5")

    def test_excludes_zero_quantity(self, db_session):
        db_session.add(_position(ACCOUNT, "ETH", Decimal("0")))
        db_session.commit()

        result = get_open_positions(db_session, ACCOUNT)

        assert result == []

    def test_excludes_other_account(self, db_session):
        db_session.add(_position(OTHER, "BTC", Decimal("2")))
        db_session.commit()

        result = get_open_positions(db_session, ACCOUNT)

        assert result == []

    def test_empty_when_no_data(self, db_session):
        assert get_open_positions(db_session, ACCOUNT) == []

    def test_quantity_is_decimal(self, db_session):
        db_session.add(_position(ACCOUNT, "BTC", Decimal("1")))
        db_session.commit()

        result = get_open_positions(db_session, ACCOUNT)

        assert isinstance(result[0].quantity, Decimal)
        assert isinstance(result[0].avg_entry_price, Decimal)

    def test_avg_entry_price_value(self, db_session):
        db_session.add(_position(ACCOUNT, "BTC", Decimal("1"), avg_entry_price=Decimal("50000")))
        db_session.commit()

        result = get_open_positions(db_session, ACCOUNT)

        assert result[0].avg_entry_price == Decimal("50000")

    def test_multiple_open_positions_returned(self, db_session):
        db_session.add(_position(ACCOUNT, "BTC", Decimal("1")))
        db_session.add(_position(ACCOUNT, "ETH", Decimal("2")))
        db_session.add(_position(ACCOUNT, "SOL", Decimal("0")))  # excluded
        db_session.commit()

        result = get_open_positions(db_session, ACCOUNT)

        symbols = {r.symbol for r in result}
        assert symbols == {"BTC", "ETH"}


# ---------------------------------------------------------------------------
# get_pnl_summary
# ---------------------------------------------------------------------------


class TestGetPnlSummary:
    def test_sums_realized_pnl(self, db_session):
        db_session.add(_pnl(ACCOUNT, Decimal("100"), Decimal("0")))
        db_session.add(_pnl(ACCOUNT, Decimal("200"), Decimal("0")))
        db_session.commit()

        result = get_pnl_summary(db_session, ACCOUNT)

        assert result.total_realized_pnl == Decimal("300")

    def test_sums_unrealized_pnl(self, db_session):
        db_session.add(_pnl(ACCOUNT, Decimal("0"), Decimal("50")))
        db_session.add(_pnl(ACCOUNT, Decimal("0"), Decimal("75")))
        db_session.commit()

        result = get_pnl_summary(db_session, ACCOUNT)

        assert result.total_unrealized_pnl == Decimal("125")

    def test_sums_funding_paid(self, db_session):
        db_session.add(_funding(ACCOUNT, Decimal("-10")))
        db_session.add(_funding(ACCOUNT, Decimal("-5")))
        db_session.commit()

        result = get_pnl_summary(db_session, ACCOUNT)

        assert result.total_funding_paid == Decimal("-15")

    def test_net_pnl_is_sum_of_components(self, db_session):
        db_session.add(_pnl(ACCOUNT, Decimal("100"), Decimal("50")))
        db_session.add(_funding(ACCOUNT, Decimal("-15")))
        db_session.commit()

        result = get_pnl_summary(db_session, ACCOUNT)

        assert result.net_pnl == Decimal("135")  # 100 + 50 - 15

    def test_excludes_other_account_pnl(self, db_session):
        db_session.add(_pnl(ACCOUNT, Decimal("100"), Decimal("0")))
        db_session.add(_pnl(OTHER, Decimal("999"), Decimal("0")))
        db_session.commit()

        result = get_pnl_summary(db_session, ACCOUNT)

        assert result.total_realized_pnl == Decimal("100")

    def test_excludes_other_account_funding(self, db_session):
        db_session.add(_funding(ACCOUNT, Decimal("-10")))
        db_session.add(_funding(OTHER, Decimal("-999")))
        db_session.commit()

        result = get_pnl_summary(db_session, ACCOUNT)

        assert result.total_funding_paid == Decimal("-10")

    def test_zero_result_when_no_data(self, db_session):
        result = get_pnl_summary(db_session, ACCOUNT)

        assert result.total_realized_pnl == Decimal("0")
        assert result.total_unrealized_pnl == Decimal("0")
        assert result.total_funding_paid == Decimal("0")
        assert result.net_pnl == Decimal("0")

    def test_all_fields_are_decimal(self, db_session):
        result = get_pnl_summary(db_session, ACCOUNT)

        assert isinstance(result, PnLSummaryRow)
        assert isinstance(result.total_realized_pnl, Decimal)
        assert isinstance(result.total_unrealized_pnl, Decimal)
        assert isinstance(result.total_funding_paid, Decimal)
        assert isinstance(result.net_pnl, Decimal)


# ---------------------------------------------------------------------------
# get_recent_fills
# ---------------------------------------------------------------------------


class TestGetRecentFills:
    def test_returns_fill_for_account(self, db_session):
        intent, orec, fill = _fill_chain(ACCOUNT, Decimal("100"), Decimal("1"), Decimal("0.05"))
        db_session.add(intent)
        db_session.add(orec)
        db_session.add(fill)
        db_session.commit()

        result = get_recent_fills(db_session, ACCOUNT)

        assert len(result) == 1
        assert isinstance(result[0], FillRow)
        assert result[0].symbol == "BTC"
        assert result[0].side == "buy"
        assert result[0].fill_price == Decimal("100")
        assert result[0].fill_qty == Decimal("1")
        assert result[0].fee_amount == Decimal("0.05")

    def test_excludes_other_account(self, db_session):
        intent, orec, fill = _fill_chain(OTHER)
        db_session.add(intent)
        db_session.add(orec)
        db_session.add(fill)
        db_session.commit()

        result = get_recent_fills(db_session, ACCOUNT)

        assert result == []

    def test_respects_limit(self, db_session):
        for _ in range(5):
            intent, orec, fill = _fill_chain(ACCOUNT)
            db_session.add(intent)
            db_session.add(orec)
            db_session.add(fill)
        db_session.commit()

        result = get_recent_fills(db_session, ACCOUNT, limit=3)

        assert len(result) == 3

    def test_empty_when_no_data(self, db_session):
        assert get_recent_fills(db_session, ACCOUNT) == []

    def test_fill_price_is_decimal(self, db_session):
        intent, orec, fill = _fill_chain(ACCOUNT, fill_price=Decimal("48000.5"))
        db_session.add(intent)
        db_session.add(orec)
        db_session.add(fill)
        db_session.commit()

        result = get_recent_fills(db_session, ACCOUNT)

        assert isinstance(result[0].fill_price, Decimal)
        assert isinstance(result[0].fill_qty, Decimal)
        assert isinstance(result[0].fee_amount, Decimal)

    def test_default_limit_is_20(self, db_session):
        for _ in range(25):
            intent, orec, fill = _fill_chain(ACCOUNT)
            db_session.add(intent)
            db_session.add(orec)
            db_session.add(fill)
        db_session.commit()

        result = get_recent_fills(db_session, ACCOUNT)

        assert len(result) == 20


# ---------------------------------------------------------------------------
# get_risk_events
# ---------------------------------------------------------------------------


class TestGetRiskEvents:
    def test_returns_event_for_account(self, db_session):
        db_session.add(_risk_event(ACCOUNT))
        db_session.commit()

        result = get_risk_events(db_session, ACCOUNT)

        assert len(result) == 1
        assert isinstance(result[0], RiskEventRow)
        assert result[0].rule_name == "max_notional"
        assert result[0].event_type == "limit_breached"
        assert result[0].severity == "warn"

    def test_details_is_dict(self, db_session):
        db_session.add(_risk_event(ACCOUNT))
        db_session.commit()

        result = get_risk_events(db_session, ACCOUNT)

        assert isinstance(result[0].details, dict)
        assert result[0].details == {"threshold": 1000, "actual": 1500}

    def test_excludes_other_account(self, db_session):
        db_session.add(_risk_event(OTHER))
        db_session.commit()

        result = get_risk_events(db_session, ACCOUNT)

        assert result == []

    def test_respects_limit(self, db_session):
        for _ in range(10):
            db_session.add(_risk_event(ACCOUNT))
        db_session.commit()

        result = get_risk_events(db_session, ACCOUNT, limit=4)

        assert len(result) == 4

    def test_empty_when_no_data(self, db_session):
        assert get_risk_events(db_session, ACCOUNT) == []

    def test_default_limit_is_50(self, db_session):
        for _ in range(60):
            db_session.add(_risk_event(ACCOUNT))
        db_session.commit()

        result = get_risk_events(db_session, ACCOUNT)

        assert len(result) == 50


# ---------------------------------------------------------------------------
# get_run_summary
# ---------------------------------------------------------------------------


class TestGetRunSummary:
    def test_combines_all_components(self, db_session):
        db_session.add(_position(ACCOUNT, "BTC", Decimal("1")))
        db_session.add(_position(ACCOUNT, "ETH", Decimal("2")))
        db_session.add(_pnl(ACCOUNT, Decimal("100"), Decimal("20")))
        db_session.add(_funding(ACCOUNT, Decimal("-5")))
        intent, orec, fill = _fill_chain(ACCOUNT)
        db_session.add(intent)
        db_session.add(orec)
        db_session.add(fill)
        db_session.add(_risk_event(ACCOUNT))
        db_session.commit()

        result = get_run_summary(db_session, ACCOUNT)

        assert isinstance(result, RunSummaryRow)
        assert result.account_name == ACCOUNT
        assert result.open_position_count == 2
        assert result.total_fills == 1
        assert result.total_risk_events == 1
        assert result.realized_pnl == Decimal("100")
        assert result.unrealized_pnl == Decimal("20")
        assert result.funding_paid == Decimal("-5")
        assert result.net_pnl == Decimal("115")  # 100 + 20 - 5

    def test_excludes_other_account(self, db_session):
        db_session.add(_position(OTHER, "BTC", Decimal("5")))
        db_session.add(_pnl(OTHER, Decimal("999"), Decimal("999")))
        db_session.add(_funding(OTHER, Decimal("-999")))
        intent, orec, fill = _fill_chain(OTHER)
        db_session.add(intent)
        db_session.add(orec)
        db_session.add(fill)
        db_session.add(_risk_event(OTHER))
        db_session.commit()

        result = get_run_summary(db_session, ACCOUNT)

        assert result.open_position_count == 0
        assert result.total_fills == 0
        assert result.total_risk_events == 0
        assert result.realized_pnl == Decimal("0")
        assert result.net_pnl == Decimal("0")

    def test_zero_result_when_no_data(self, db_session):
        result = get_run_summary(db_session, ACCOUNT)

        assert result.account_name == ACCOUNT
        assert result.open_position_count == 0
        assert result.total_fills == 0
        assert result.total_risk_events == 0
        assert result.net_pnl == Decimal("0")

    def test_all_numeric_fields_are_decimal(self, db_session):
        result = get_run_summary(db_session, ACCOUNT)

        assert isinstance(result.realized_pnl, Decimal)
        assert isinstance(result.unrealized_pnl, Decimal)
        assert isinstance(result.funding_paid, Decimal)
        assert isinstance(result.net_pnl, Decimal)
