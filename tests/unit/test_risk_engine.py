from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

from core.models.order_intent import OrderIntent
from core.models.risk_event import RiskEvent
from core.risk.engine import RiskCheckResult, RiskConfig, RiskEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(**overrides) -> RiskConfig:
    defaults = dict(
        max_data_age_seconds=300,
        min_entry_funding_rate=Decimal("0.0001"),
        max_notional_per_symbol=Decimal("100000"),
        kill_switch_active=False,
    )
    defaults.update(overrides)
    return RiskConfig(**defaults)


def _entry_intent(*, qty: str = "1") -> OrderIntent:
    """Entry intent: reduce_only=False."""
    return OrderIntent(
        strategy_signal_id=None,
        portfolio_id=None,
        mode="paper",
        exchange="binance",
        symbol="BTC-PERP",
        side="sell",
        order_type="market",
        time_in_force=None,
        quantity=Decimal(qty),
        limit_price=None,
        reduce_only=False,
        post_only=False,
        client_order_id=None,
        status="pending",
        created_ts=datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc),
    )


def _exit_intent(*, qty: str = "1") -> OrderIntent:
    """Exit intent: reduce_only=True."""
    return OrderIntent(
        strategy_signal_id=None,
        portfolio_id=None,
        mode="paper",
        exchange="binance",
        symbol="BTC-PERP",
        side="buy",
        order_type="market",
        time_in_force=None,
        quantity=Decimal(qty),
        limit_price=None,
        reduce_only=True,
        post_only=False,
        client_order_id=None,
        status="pending",
        created_ts=datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc),
    )


def _fresh_ts() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=10)


def _stale_ts(max_age_seconds: int = 300) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds + 100)


_MARK = Decimal("50000")
_RATE_ABOVE = Decimal("0.0002")   # above default min_entry_funding_rate of 0.0001
_RATE_BELOW = Decimal("0.00003")  # below default min_entry_funding_rate of 0.0001


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def test_kill_switch_blocks_all_intents() -> None:
    session = Mock()
    engine = RiskEngine(_config(kill_switch_active=True))

    result = engine.check(
        session=session,
        order_intent=_entry_intent(),
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )

    assert result.passed is False
    assert result.reason == "kill_switch_active"
    assert isinstance(result.risk_event, RiskEvent)
    session.add.assert_called_once()


# ---------------------------------------------------------------------------
# Stale data
# ---------------------------------------------------------------------------

def test_stale_data_blocks_when_data_is_old() -> None:
    session = Mock()
    engine = RiskEngine(_config())

    result = engine.check(
        session=session,
        order_intent=_entry_intent(),
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_stale_ts(300),
    )

    assert result.passed is False
    assert result.reason == "stale_funding_data"
    session.add.assert_called_once()


def test_stale_data_passes_when_data_is_fresh() -> None:
    session = Mock()
    engine = RiskEngine(_config())

    result = engine.check(
        session=session,
        order_intent=_entry_intent(),
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )

    assert result.passed is True
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Funding edge
# ---------------------------------------------------------------------------

def test_funding_edge_blocks_entry_intent_below_threshold() -> None:
    session = Mock()
    engine = RiskEngine(_config())

    result = engine.check(
        session=session,
        order_intent=_entry_intent(),
        funding_rate=_RATE_BELOW,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )

    assert result.passed is False
    assert result.reason == "funding_below_threshold"
    session.add.assert_called_once()


def test_funding_edge_does_not_block_exit_intent_below_threshold() -> None:
    """reduce_only=True (exit) bypasses the funding edge check."""
    session = Mock()
    engine = RiskEngine(_config())

    result = engine.check(
        session=session,
        order_intent=_exit_intent(qty="1"),
        funding_rate=_RATE_BELOW,   # would block an entry
        mark_price=_MARK,           # notional = 50 000 < 100 000
        latest_funding_ts=_fresh_ts(),
    )

    assert result.passed is True
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Max notional
# ---------------------------------------------------------------------------

def test_max_notional_blocks_when_exceeded() -> None:
    session = Mock()
    engine = RiskEngine(_config(max_notional_per_symbol=Decimal("100000")))

    # qty=10, mark=50000 -> notional=500000 > 100000
    result = engine.check(
        session=session,
        order_intent=_entry_intent(qty="10"),
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )

    assert result.passed is False
    assert result.reason == "max_notional_exceeded"
    session.add.assert_called_once()


def test_max_notional_passes_when_within_limit() -> None:
    session = Mock()
    engine = RiskEngine(_config(max_notional_per_symbol=Decimal("100000")))

    # qty=1, mark=50000 -> notional=50000 < 100000
    result = engine.check(
        session=session,
        order_intent=_entry_intent(qty="1"),
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )

    assert result.passed is True
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# All pass
# ---------------------------------------------------------------------------

def test_all_checks_pass_returns_passed_result() -> None:
    session = Mock()
    engine = RiskEngine(_config())

    result = engine.check(
        session=session,
        order_intent=_entry_intent(qty="1"),
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )

    assert result.passed is True
    assert result.reason is None
    assert result.risk_event is None
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# RiskEvent persistence
# ---------------------------------------------------------------------------

def test_failed_check_persists_exactly_one_risk_event() -> None:
    session = Mock()
    engine = RiskEngine(_config(kill_switch_active=True))

    result = engine.check(
        session=session,
        order_intent=_entry_intent(),
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )

    assert result.passed is False
    assert session.add.call_count == 1
    added = session.add.call_args.args[0]
    assert isinstance(added, RiskEvent)
    assert added.rule_name == "kill_switch_active"


# ---------------------------------------------------------------------------
# Check ordering
# ---------------------------------------------------------------------------

def test_kill_switch_evaluated_before_stale_data() -> None:
    """Kill switch fires even when data is also stale — kill switch is first."""
    session = Mock()
    engine = RiskEngine(_config(kill_switch_active=True))

    result = engine.check(
        session=session,
        order_intent=_entry_intent(),
        funding_rate=_RATE_BELOW,
        mark_price=_MARK,
        latest_funding_ts=_stale_ts(),  # also stale
    )

    assert result.reason == "kill_switch_active"
    assert session.add.call_count == 1  # only one RiskEvent, not two
