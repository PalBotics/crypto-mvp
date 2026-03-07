from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from core.alerting.evaluator import AlertConfig, AlertEvaluator
from core.models.funding_payment import FundingPayment
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.order_intent import OrderIntent
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent

ACCOUNT = "alert_group_d"
EXCHANGE = "test_exchange"
SPOT_SYMBOL = "BTC-USD"
PERP_SYMBOL = "BTC-PERP"
NOW = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)


def _config(**overrides) -> AlertConfig:
    defaults = dict(
        exchange=EXCHANGE,
        symbol=PERP_SYMBOL,
        account_name=ACCOUNT,
        stale_data_threshold_seconds=300,
        drawdown_threshold=Decimal("-500"),
        no_fill_threshold_seconds=3600,
        min_funding_rate=Decimal("0.0001"),
        spot_symbol="",
        perp_symbol="",
        mismatch_tolerance=Decimal("0.01"),
    )
    defaults.update(overrides)
    return AlertConfig(**defaults)


def _add_funding_snapshot(session, event_ts: datetime, funding_rate: Decimal) -> None:
    session.add(
        FundingRateSnapshot(
            id=uuid.uuid4(),
            exchange=EXCHANGE,
            adapter_name="test",
            symbol=PERP_SYMBOL,
            exchange_symbol=PERP_SYMBOL,
            funding_rate=funding_rate,
            funding_interval_hours=8,
            predicted_funding_rate=None,
            mark_price=Decimal("50000"),
            index_price=Decimal("50000"),
            next_funding_ts=None,
            event_ts=event_ts,
            ingested_ts=event_ts,
        )
    )


def _add_order_intent(
    session,
    *,
    status: str,
    created_ts: datetime,
    mode: str = ACCOUNT,
) -> None:
    session.add(
        OrderIntent(
            id=uuid.uuid4(),
            strategy_signal_id=None,
            portfolio_id=None,
            mode=mode,
            exchange=EXCHANGE,
            symbol=PERP_SYMBOL,
            side="sell",
            order_type="market",
            time_in_force=None,
            quantity=Decimal("1"),
            limit_price=None,
            reduce_only=False,
            post_only=False,
            client_order_id=None,
            status=status,
            created_ts=created_ts,
        )
    )


def _add_kill_switch_event(session, created_ts: datetime, account_name: str = ACCOUNT) -> None:
    session.add(
        RiskEvent(
            id=uuid.uuid4(),
            event_type="risk_block",
            severity="high",
            strategy_name=account_name,
            symbol=PERP_SYMBOL,
            rule_name="kill_switch_active",
            details_json={"reason": "manual"},
            created_ts=created_ts,
        )
    )


def _add_position(
    session,
    *,
    symbol: str,
    quantity: Decimal,
    snapshot_ts: datetime,
    account_name: str = ACCOUNT,
) -> None:
    session.add(
        PositionSnapshot(
            id=uuid.uuid4(),
            exchange=EXCHANGE,
            account_name=account_name,
            symbol=symbol,
            instrument_type="spot" if symbol == SPOT_SYMBOL else "future",
            side="long" if symbol == SPOT_SYMBOL else "short",
            quantity=quantity,
            avg_entry_price=Decimal("50000"),
            mark_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            leverage=Decimal("1"),
            margin_used=Decimal("100"),
            snapshot_ts=snapshot_ts,
        )
    )


def _add_daily_pnl(session, ts: datetime, realized: Decimal, account_name: str = ACCOUNT) -> None:
    session.add(
        PnLSnapshot(
            id=uuid.uuid4(),
            portfolio_id=None,
            strategy_name=account_name,
            symbol=PERP_SYMBOL,
            realized_pnl=realized,
            unrealized_pnl=Decimal("0"),
            funding_pnl=Decimal("0"),
            fee_pnl=Decimal("0"),
            gross_pnl=realized,
            net_pnl=realized,
            snapshot_ts=ts,
        )
    )


def _add_funding_payment(session, ts: datetime, amount: Decimal, account_name: str = ACCOUNT) -> None:
    session.add(
        FundingPayment(
            id=uuid.uuid4(),
            exchange=EXCHANGE,
            symbol=PERP_SYMBOL,
            account_name=account_name,
            position_quantity=Decimal("1"),
            mark_price=Decimal("50000"),
            funding_rate=Decimal("0.0001"),
            payment_amount=amount,
            accrued_ts=ts,
            created_ts=ts,
        )
    )


# ---------------------------------------------------------------------------
# exchange_disconnected
# ---------------------------------------------------------------------------


def test_exchange_disconnected_triggers_when_data_is_2x_stale(db_session) -> None:
    _add_funding_snapshot(
        db_session,
        event_ts=NOW - timedelta(seconds=601),
        funding_rate=Decimal("0.0002"),
    )
    db_session.commit()

    evaluator = AlertEvaluator(_config(stale_data_threshold_seconds=300))
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "exchange_disconnected"]
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"


def test_exchange_disconnected_does_not_trigger_at_1x_stale(db_session) -> None:
    _add_funding_snapshot(
        db_session,
        event_ts=NOW - timedelta(seconds=301),
        funding_rate=Decimal("0.0002"),
    )
    db_session.commit()

    evaluator = AlertEvaluator(_config(stale_data_threshold_seconds=300))
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "exchange_disconnected"]
    assert alerts == []


def test_exchange_disconnected_persists_one_risk_event(db_session) -> None:
    _add_funding_snapshot(
        db_session,
        event_ts=NOW - timedelta(seconds=700),
        funding_rate=Decimal("0.0002"),
    )
    db_session.commit()

    evaluator = AlertEvaluator(_config(stale_data_threshold_seconds=300))
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "exchange_disconnected"]
    assert len(alerts) == 1
    assert alerts[0].risk_event is not None
    assert alerts[0].risk_event.rule_name == "exchange_disconnected"


# ---------------------------------------------------------------------------
# order_rejected
# ---------------------------------------------------------------------------


def test_order_rejected_triggers_when_recent_rejects_exist(db_session) -> None:
    _add_order_intent(
        db_session,
        status="rejected",
        created_ts=NOW - timedelta(seconds=120),
    )
    db_session.commit()

    evaluator = AlertEvaluator(_config(no_fill_threshold_seconds=3600))
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "order_rejected"]
    assert len(alerts) == 1
    assert "1 rejected" in alerts[0].message


def test_order_rejected_does_not_trigger_when_no_recent_rejects(db_session) -> None:
    _add_order_intent(
        db_session,
        status="rejected",
        created_ts=NOW - timedelta(seconds=4000),
    )
    db_session.commit()

    evaluator = AlertEvaluator(_config(no_fill_threshold_seconds=3600))
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "order_rejected"]
    assert alerts == []


def test_order_rejected_is_log_only_no_risk_event(db_session) -> None:
    _add_order_intent(
        db_session,
        status="rejected",
        created_ts=NOW - timedelta(seconds=30),
    )
    db_session.commit()

    evaluator = AlertEvaluator(_config())
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "order_rejected"]
    assert len(alerts) == 1
    assert alerts[0].risk_event is None


# ---------------------------------------------------------------------------
# strategy_disabled
# ---------------------------------------------------------------------------


def test_strategy_disabled_triggers_when_kill_switch_newer_than_last_fill(db_session) -> None:
    _add_order_intent(
        db_session,
        status="filled",
        created_ts=NOW - timedelta(minutes=30),
    )
    _add_kill_switch_event(db_session, created_ts=NOW - timedelta(minutes=5))
    db_session.commit()

    evaluator = AlertEvaluator(_config())
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "strategy_disabled"]
    assert len(alerts) == 1
    assert alerts[0].severity == "warning"


def test_strategy_disabled_does_not_trigger_when_fill_after_kill_switch(db_session) -> None:
    _add_kill_switch_event(db_session, created_ts=NOW - timedelta(minutes=30))
    _add_order_intent(
        db_session,
        status="filled",
        created_ts=NOW - timedelta(minutes=5),
    )
    db_session.commit()

    evaluator = AlertEvaluator(_config())
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "strategy_disabled"]
    assert alerts == []


def test_strategy_disabled_is_log_only_no_risk_event(db_session) -> None:
    _add_kill_switch_event(db_session, created_ts=NOW - timedelta(minutes=1))
    db_session.commit()

    evaluator = AlertEvaluator(_config())
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "strategy_disabled"]
    assert len(alerts) == 1
    assert alerts[0].risk_event is None


# ---------------------------------------------------------------------------
# position_mismatch
# ---------------------------------------------------------------------------


def test_position_mismatch_triggers_when_one_leg_zero(db_session) -> None:
    _add_position(
        db_session,
        symbol=SPOT_SYMBOL,
        quantity=Decimal("1"),
        snapshot_ts=NOW - timedelta(minutes=1),
    )
    _add_position(
        db_session,
        symbol=PERP_SYMBOL,
        quantity=Decimal("0"),
        snapshot_ts=NOW - timedelta(minutes=1),
    )
    db_session.commit()

    evaluator = AlertEvaluator(
        _config(
            spot_symbol=SPOT_SYMBOL,
            perp_symbol=PERP_SYMBOL,
            mismatch_tolerance=Decimal("0.01"),
        )
    )
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "position_mismatch"]
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"


def test_position_mismatch_triggers_when_difference_above_tolerance(db_session) -> None:
    _add_position(
        db_session,
        symbol=SPOT_SYMBOL,
        quantity=Decimal("1.00"),
        snapshot_ts=NOW - timedelta(minutes=1),
    )
    _add_position(
        db_session,
        symbol=PERP_SYMBOL,
        quantity=Decimal("0.80"),
        snapshot_ts=NOW - timedelta(minutes=1),
    )
    db_session.commit()

    evaluator = AlertEvaluator(
        _config(
            spot_symbol=SPOT_SYMBOL,
            perp_symbol=PERP_SYMBOL,
            mismatch_tolerance=Decimal("0.01"),
        )
    )
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "position_mismatch"]
    assert len(alerts) == 1


def test_position_mismatch_does_not_trigger_when_balanced_within_tolerance(db_session) -> None:
    _add_position(
        db_session,
        symbol=SPOT_SYMBOL,
        quantity=Decimal("1.00"),
        snapshot_ts=NOW - timedelta(minutes=1),
    )
    _add_position(
        db_session,
        symbol=PERP_SYMBOL,
        quantity=Decimal("0.995"),
        snapshot_ts=NOW - timedelta(minutes=1),
    )
    db_session.commit()

    evaluator = AlertEvaluator(
        _config(
            spot_symbol=SPOT_SYMBOL,
            perp_symbol=PERP_SYMBOL,
            mismatch_tolerance=Decimal("0.01"),
        )
    )
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "position_mismatch"]
    assert alerts == []


def test_position_mismatch_persists_one_risk_event(db_session) -> None:
    _add_position(
        db_session,
        symbol=SPOT_SYMBOL,
        quantity=Decimal("0"),
        snapshot_ts=NOW - timedelta(minutes=1),
    )
    _add_position(
        db_session,
        symbol=PERP_SYMBOL,
        quantity=Decimal("1"),
        snapshot_ts=NOW - timedelta(minutes=1),
    )
    db_session.commit()

    evaluator = AlertEvaluator(
        _config(
            spot_symbol=SPOT_SYMBOL,
            perp_symbol=PERP_SYMBOL,
            mismatch_tolerance=Decimal("0.01"),
        )
    )
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "position_mismatch"]
    assert len(alerts) == 1
    assert alerts[0].risk_event is not None
    assert alerts[0].risk_event.rule_name == "position_mismatch"


# ---------------------------------------------------------------------------
# daily_loss_threshold_hit
# ---------------------------------------------------------------------------


def test_daily_loss_threshold_hit_triggers_when_day_loss_exceeded(db_session) -> None:
    day_start = NOW.replace(hour=0, minute=0, second=0, microsecond=0)

    # Keep cumulative net above threshold so this test isolates the daily-only condition.
    _add_daily_pnl(db_session, ts=day_start - timedelta(hours=2), realized=Decimal("1000"))
    _add_daily_pnl(db_session, ts=day_start + timedelta(hours=1), realized=Decimal("-700"))
    db_session.commit()

    evaluator = AlertEvaluator(_config(drawdown_threshold=Decimal("-500")))
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "daily_loss_threshold_hit"]
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"


def test_daily_loss_threshold_hit_does_not_trigger_when_within_threshold(db_session) -> None:
    day_start = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    _add_daily_pnl(db_session, ts=day_start + timedelta(hours=1), realized=Decimal("-200"))
    _add_funding_payment(db_session, ts=day_start + timedelta(hours=2), amount=Decimal("-50"))
    db_session.commit()

    evaluator = AlertEvaluator(_config(drawdown_threshold=Decimal("-500")))
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "daily_loss_threshold_hit"]
    assert alerts == []


def test_daily_loss_threshold_hit_persists_one_risk_event(db_session) -> None:
    day_start = NOW.replace(hour=0, minute=0, second=0, microsecond=0)

    _add_daily_pnl(db_session, ts=day_start - timedelta(hours=2), realized=Decimal("900"))
    _add_daily_pnl(db_session, ts=day_start + timedelta(hours=1), realized=Decimal("-800"))
    _add_funding_payment(db_session, ts=day_start + timedelta(hours=2), amount=Decimal("-50"))
    db_session.commit()

    evaluator = AlertEvaluator(_config(drawdown_threshold=Decimal("-500")))
    results = evaluator.evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "daily_loss_threshold_hit"]
    assert len(alerts) == 1
    assert alerts[0].risk_event is not None
    assert alerts[0].risk_event.rule_name == "daily_loss_threshold_hit"


# ---------------------------------------------------------------------------
# config defaults
# ---------------------------------------------------------------------------


def test_new_alert_config_fields_have_working_defaults(db_session) -> None:
    _add_funding_snapshot(
        db_session,
        event_ts=NOW - timedelta(seconds=301),
        funding_rate=Decimal("0.0002"),
    )
    db_session.commit()

    # Should construct without explicitly providing new Group D fields.
    evaluator = AlertEvaluator(
        AlertConfig(
            exchange=EXCHANGE,
            symbol=PERP_SYMBOL,
            account_name=ACCOUNT,
            stale_data_threshold_seconds=300,
            drawdown_threshold=Decimal("-500"),
            no_fill_threshold_seconds=3600,
            min_funding_rate=Decimal("0.0001"),
        )
    )
    results = evaluator.evaluate(db_session, now=NOW)

    assert isinstance(results, list)
