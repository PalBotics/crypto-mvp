"""Unit tests for core/alerting/evaluator.py.

Each test class covers one alert condition independently.
Tests use the db_session fixture from tests/unit/conftest.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.alerting.evaluator import AlertConfig, AlertEvaluator, AlertResult
from core.models.fill_record import FillRecord
from core.models.funding_payment import FundingPayment
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent

ACCOUNT = "alert_test_run"
EXCHANGE = "test_exchange"
SYMBOL = "BTC-PERP"
NOW = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)


def _make_config(**overrides) -> AlertConfig:
    defaults = dict(
        exchange=EXCHANGE,
        symbol=SYMBOL,
        account_name=ACCOUNT,
        stale_data_threshold_seconds=300,
        drawdown_threshold=Decimal("-500"),
        no_fill_threshold_seconds=3600,
        min_funding_rate=Decimal("0.0001"),
    )
    defaults.update(overrides)
    return AlertConfig(**defaults)


def _add_funding_snapshot(
    session,
    event_ts: datetime,
    funding_rate: Decimal = Decimal("0.0005"),
    exchange: str = EXCHANGE,
    symbol: str = SYMBOL,
) -> FundingRateSnapshot:
    snap = FundingRateSnapshot(
        id=uuid.uuid4(),
        exchange=exchange,
        adapter_name="test",
        symbol=symbol,
        exchange_symbol=symbol,
        funding_rate=funding_rate,
        event_ts=event_ts,
        ingested_ts=NOW,
    )
    session.add(snap)
    return snap


def _add_pnl(session, account_name: str, realized: Decimal, unrealized: Decimal = Decimal("0")) -> PnLSnapshot:
    snap = PnLSnapshot(
        id=uuid.uuid4(),
        strategy_name=account_name,
        symbol=SYMBOL,
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


def _add_funding_payment(session, account_name: str, amount: Decimal) -> FundingPayment:
    fp = FundingPayment(
        id=uuid.uuid4(),
        exchange=EXCHANGE,
        symbol=SYMBOL,
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


def _add_position(session, account_name: str, quantity: Decimal) -> PositionSnapshot:
    pos = PositionSnapshot(
        id=uuid.uuid4(),
        exchange=EXCHANGE,
        symbol=SYMBOL,
        account_name=account_name,
        instrument_type="perp",
        side="long",
        quantity=quantity,
        snapshot_ts=NOW,
    )
    session.add(pos)
    return pos


def _add_fill_chain(
    session,
    account_name: str,
    fill_ts: datetime,
) -> tuple[OrderIntent, OrderRecord, FillRecord]:
    intent = OrderIntent(
        id=uuid.uuid4(),
        mode=account_name,
        exchange=EXCHANGE,
        symbol=SYMBOL,
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        reduce_only=False,
        post_only=False,
        status="filled",
        created_ts=fill_ts,
    )
    orec = OrderRecord(
        id=uuid.uuid4(),
        order_intent_id=intent.id,
        exchange=EXCHANGE,
        symbol=SYMBOL,
        exchange_order_id=str(uuid.uuid4()),
        side="buy",
        order_type="market",
        status="filled",
        submitted_qty=Decimal("1"),
        filled_qty=Decimal("1"),
        avg_fill_price=Decimal("100"),
        fees_paid=Decimal("0.05"),
        raw_exchange_payload={},
        created_ts=fill_ts,
        updated_ts=fill_ts,
    )
    fill = FillRecord(
        id=uuid.uuid4(),
        order_record_id=orec.id,
        exchange=EXCHANGE,
        symbol=SYMBOL,
        side="buy",
        fill_price=Decimal("100"),
        fill_qty=Decimal("1"),
        fill_notional=Decimal("100"),
        fee_paid=Decimal("0.05"),
        fill_ts=fill_ts,
        ingested_ts=fill_ts,
    )
    session.add(intent)
    session.add(orec)
    session.add(fill)
    return intent, orec, fill


# ---------------------------------------------------------------------------
# stale_funding_data
# ---------------------------------------------------------------------------


class TestStaleFundingData:
    def test_triggers_when_no_snapshot_exists(self, db_session):
        evaluator = AlertEvaluator(_make_config())
        results = evaluator.evaluate(db_session, now=NOW)

        stale = [r for r in results if r.alert_type == "stale_funding_data"]
        assert len(stale) == 1
        assert stale[0].severity == "warning"
        assert stale[0].risk_event is None

    def test_triggers_when_snapshot_is_too_old(self, db_session):
        old_ts = NOW - timedelta(seconds=600)  # 600s > 300s threshold
        _add_funding_snapshot(db_session, event_ts=old_ts)
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(stale_data_threshold_seconds=300))
        results = evaluator.evaluate(db_session, now=NOW)

        stale = [r for r in results if r.alert_type == "stale_funding_data"]
        assert len(stale) == 1
        assert stale[0].severity == "warning"
        assert stale[0].risk_event is None

    def test_does_not_trigger_when_snapshot_is_fresh(self, db_session):
        recent_ts = NOW - timedelta(seconds=60)  # well within 300s threshold
        _add_funding_snapshot(db_session, event_ts=recent_ts)
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(stale_data_threshold_seconds=300))
        results = evaluator.evaluate(db_session, now=NOW)

        stale = [r for r in results if r.alert_type == "stale_funding_data"]
        assert stale == []

    def test_message_contains_exchange_and_symbol(self, db_session):
        evaluator = AlertEvaluator(_make_config())
        results = evaluator.evaluate(db_session, now=NOW)

        stale = [r for r in results if r.alert_type == "stale_funding_data"]
        assert EXCHANGE in stale[0].message
        assert SYMBOL in stale[0].message


# ---------------------------------------------------------------------------
# position_pnl_drawdown
# ---------------------------------------------------------------------------


class TestPositionPnlDrawdown:
    def test_triggers_when_net_below_threshold(self, db_session):
        _add_pnl(db_session, ACCOUNT, realized=Decimal("-200"))
        _add_funding_payment(db_session, ACCOUNT, amount=Decimal("-400"))
        db_session.commit()

        # net = -200 + (-400) = -600 < -500 threshold
        evaluator = AlertEvaluator(_make_config(drawdown_threshold=Decimal("-500")))
        results = evaluator.evaluate(db_session, now=NOW)

        drawdown = [r for r in results if r.alert_type == "position_pnl_drawdown"]
        assert len(drawdown) == 1
        assert drawdown[0].severity == "critical"

    def test_persists_risk_event_on_trigger(self, db_session):
        _add_pnl(db_session, ACCOUNT, realized=Decimal("-200"))
        _add_funding_payment(db_session, ACCOUNT, amount=Decimal("-400"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(drawdown_threshold=Decimal("-500")))
        results = evaluator.evaluate(db_session, now=NOW)

        drawdown = [r for r in results if r.alert_type == "position_pnl_drawdown"]
        assert drawdown[0].risk_event is not None
        risk_ev = drawdown[0].risk_event
        assert isinstance(risk_ev, RiskEvent)
        assert risk_ev.rule_name == "position_pnl_drawdown"
        assert risk_ev.event_type == "alert"
        assert risk_ev.severity == "critical"
        assert risk_ev.strategy_name == ACCOUNT

    def test_risk_event_details_json_contains_pnl_values(self, db_session):
        _add_pnl(db_session, ACCOUNT, realized=Decimal("-200"))
        _add_funding_payment(db_session, ACCOUNT, amount=Decimal("-400"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(drawdown_threshold=Decimal("-500")))
        results = evaluator.evaluate(db_session, now=NOW)

        drawdown = [r for r in results if r.alert_type == "position_pnl_drawdown"]
        details = drawdown[0].risk_event.details_json
        assert "account_name" in details
        assert "realized_pnl" in details
        assert "funding_paid" in details
        assert "net_pnl" in details
        assert "drawdown_threshold" in details

    def test_does_not_trigger_when_net_above_threshold(self, db_session):
        _add_pnl(db_session, ACCOUNT, realized=Decimal("100"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(drawdown_threshold=Decimal("-500")))
        results = evaluator.evaluate(db_session, now=NOW)

        drawdown = [r for r in results if r.alert_type == "position_pnl_drawdown"]
        assert drawdown == []

    def test_no_risk_event_when_not_triggered(self, db_session):
        evaluator = AlertEvaluator(_make_config(drawdown_threshold=Decimal("-500")))
        evaluator.evaluate(db_session, now=NOW)

        count = db_session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(
                __import__("sqlalchemy", fromlist=["func"]).func.count(RiskEvent.id)
            ).where(RiskEvent.rule_name == "position_pnl_drawdown")
        ).scalar_one()
        assert count == 0

    def test_excludes_other_account_pnl(self, db_session):
        _add_pnl(db_session, "other_account", realized=Decimal("-1000"))
        _add_funding_payment(db_session, "other_account", amount=Decimal("-1000"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(drawdown_threshold=Decimal("-500")))
        results = evaluator.evaluate(db_session, now=NOW)

        drawdown = [r for r in results if r.alert_type == "position_pnl_drawdown"]
        assert drawdown == []


# ---------------------------------------------------------------------------
# open_position_no_recent_fill
# ---------------------------------------------------------------------------


class TestOpenPositionNoRecentFill:
    def test_triggers_when_open_position_and_no_fills(self, db_session):
        _add_position(db_session, ACCOUNT, Decimal("1"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(no_fill_threshold_seconds=3600))
        results = evaluator.evaluate(db_session, now=NOW)

        no_fill = [r for r in results if r.alert_type == "open_position_no_recent_fill"]
        assert len(no_fill) == 1
        assert no_fill[0].severity == "warning"
        assert no_fill[0].risk_event is None

    def test_triggers_when_last_fill_is_stale(self, db_session):
        _add_position(db_session, ACCOUNT, Decimal("1"))
        old_fill_ts = NOW - timedelta(seconds=7200)  # 7200s > 3600s threshold
        _add_fill_chain(db_session, ACCOUNT, fill_ts=old_fill_ts)
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(no_fill_threshold_seconds=3600))
        results = evaluator.evaluate(db_session, now=NOW)

        no_fill = [r for r in results if r.alert_type == "open_position_no_recent_fill"]
        assert len(no_fill) == 1
        assert no_fill[0].severity == "warning"

    def test_does_not_trigger_when_no_open_position(self, db_session):
        # Position with quantity=0 should not trigger
        _add_position(db_session, ACCOUNT, Decimal("0"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config())
        results = evaluator.evaluate(db_session, now=NOW)

        no_fill = [r for r in results if r.alert_type == "open_position_no_recent_fill"]
        assert no_fill == []

    def test_does_not_trigger_when_fill_is_recent(self, db_session):
        _add_position(db_session, ACCOUNT, Decimal("1"))
        recent_fill_ts = NOW - timedelta(seconds=60)  # well within 3600s
        _add_fill_chain(db_session, ACCOUNT, fill_ts=recent_fill_ts)
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(no_fill_threshold_seconds=3600))
        results = evaluator.evaluate(db_session, now=NOW)

        no_fill = [r for r in results if r.alert_type == "open_position_no_recent_fill"]
        assert no_fill == []

    def test_no_risk_event_on_trigger(self, db_session):
        _add_position(db_session, ACCOUNT, Decimal("1"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config())
        results = evaluator.evaluate(db_session, now=NOW)

        no_fill = [r for r in results if r.alert_type == "open_position_no_recent_fill"]
        assert no_fill[0].risk_event is None


# ---------------------------------------------------------------------------
# no_funding_edge
# ---------------------------------------------------------------------------


class TestNoFundingEdge:
    def test_triggers_when_rate_below_min(self, db_session):
        _add_funding_snapshot(db_session, event_ts=NOW, funding_rate=Decimal("0.00005"))
        db_session.commit()

        # rate 0.00005 < min_funding_rate 0.0001
        evaluator = AlertEvaluator(_make_config(min_funding_rate=Decimal("0.0001")))
        results = evaluator.evaluate(db_session, now=NOW)

        edge = [r for r in results if r.alert_type == "no_funding_edge"]
        assert len(edge) == 1
        assert edge[0].severity == "info"
        assert edge[0].risk_event is None

    def test_does_not_trigger_when_rate_above_min(self, db_session):
        _add_funding_snapshot(db_session, event_ts=NOW, funding_rate=Decimal("0.0005"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(min_funding_rate=Decimal("0.0001")))
        results = evaluator.evaluate(db_session, now=NOW)

        edge = [r for r in results if r.alert_type == "no_funding_edge"]
        assert edge == []

    def test_does_not_trigger_when_no_snapshot(self, db_session):
        evaluator = AlertEvaluator(_make_config(min_funding_rate=Decimal("0.0001")))
        results = evaluator.evaluate(db_session, now=NOW)

        # no snapshot → no_funding_edge does not fire (stale_funding_data fires instead)
        edge = [r for r in results if r.alert_type == "no_funding_edge"]
        assert edge == []

    def test_uses_latest_snapshot_only(self, db_session):
        # Old snapshot below threshold, recent one above — should not trigger
        _add_funding_snapshot(
            db_session, event_ts=NOW - timedelta(hours=1), funding_rate=Decimal("0.00005")
        )
        _add_funding_snapshot(
            db_session, event_ts=NOW, funding_rate=Decimal("0.0005")
        )
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(min_funding_rate=Decimal("0.0001")))
        results = evaluator.evaluate(db_session, now=NOW)

        edge = [r for r in results if r.alert_type == "no_funding_edge"]
        assert edge == []

    def test_no_risk_event_on_trigger(self, db_session):
        _add_funding_snapshot(db_session, event_ts=NOW, funding_rate=Decimal("0.00005"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(min_funding_rate=Decimal("0.0001")))
        results = evaluator.evaluate(db_session, now=NOW)

        edge = [r for r in results if r.alert_type == "no_funding_edge"]
        assert edge[0].risk_event is None

    def test_message_contains_rate_and_threshold(self, db_session):
        _add_funding_snapshot(db_session, event_ts=NOW, funding_rate=Decimal("0.00005"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(min_funding_rate=Decimal("0.0001")))
        results = evaluator.evaluate(db_session, now=NOW)

        edge = [r for r in results if r.alert_type == "no_funding_edge"]
        assert "0.00005" in edge[0].message or "5E-5" in edge[0].message or "5e-5" in edge[0].message


# ---------------------------------------------------------------------------
# evaluate() — combined / ordering tests
# ---------------------------------------------------------------------------


class TestEvaluateCombined:
    def test_returns_empty_list_when_no_conditions_met(self, db_session):
        # Fresh data, no positions, no PnL losses
        _add_funding_snapshot(db_session, event_ts=NOW, funding_rate=Decimal("0.0005"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config())
        results = evaluator.evaluate(db_session, now=NOW)

        assert results == []

    def test_returns_list_of_alert_results(self, db_session):
        evaluator = AlertEvaluator(_make_config())
        results = evaluator.evaluate(db_session, now=NOW)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, AlertResult)

    def test_only_drawdown_alert_produces_risk_event(self, db_session):
        # Trigger stale data (no snapshot) + drawdown + no-fill (open pos, no fills)
        _add_pnl(db_session, ACCOUNT, realized=Decimal("-600"))
        _add_position(db_session, ACCOUNT, Decimal("1"))
        db_session.commit()

        evaluator = AlertEvaluator(_make_config(drawdown_threshold=Decimal("-500")))
        results = evaluator.evaluate(db_session, now=NOW)

        risk_event_results = [r for r in results if r.risk_event is not None]
        assert len(risk_event_results) == 1
        assert risk_event_results[0].alert_type == "position_pnl_drawdown"
