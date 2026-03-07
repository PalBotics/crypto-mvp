"""Tests for Group B risk controls: max_daily_loss, circuit_breaker, 
emergency_flatten, and hedge_leg_mismatch.

These controls are required by Gate D before live trading is permitted.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from core.models.funding_payment import FundingPayment
from core.models.order_intent import OrderIntent
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent
from core.risk.engine import RiskCheckResult, RiskConfig, RiskEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(**overrides) -> RiskConfig:
    """Build a RiskConfig with sensible defaults for testing."""
    defaults = dict(
        max_data_age_seconds=300,
        min_entry_funding_rate=Decimal("0.0001"),
        max_notional_per_symbol=Decimal("100000"),
        kill_switch_active=False,
        max_daily_loss=Decimal("-1000"),
        circuit_breaker_max_rejects=5,
        circuit_breaker_loss_threshold=Decimal("-500"),
        circuit_breaker_window_seconds=300,
        circuit_breaker_active=False,
        spot_symbol="BTC-USD",
        perp_symbol="BTC-PERP",
    )
    defaults.update(overrides)
    return RiskConfig(**defaults)


def _entry_intent(*, qty: str = "1", mode: str = "paper", symbol: str = "BTC-PERP") -> OrderIntent:
    """Entry intent: reduce_only=False."""
    return OrderIntent(
        strategy_signal_id=None,
        portfolio_id=None,
        mode=mode,
        exchange="binance",
        symbol=symbol,
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


def _exit_intent(*, qty: str = "1", mode: str = "paper", symbol: str = "BTC-PERP") -> OrderIntent:
    """Exit intent: reduce_only=True."""
    return OrderIntent(
        strategy_signal_id=None,
        portfolio_id=None,
        mode=mode,
        exchange="binance",
        symbol=symbol,
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


_MARK = Decimal("50000")
_RATE_ABOVE = Decimal("0.0002")


# ---------------------------------------------------------------------------
# Max daily loss control
# ---------------------------------------------------------------------------

def test_max_daily_loss_blocks_entry_when_daily_loss_exceeded(db_session) -> None:
    """Entry intent blocked when today's PnL < max_daily_loss threshold."""
    account = "paper"
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Create a PnL snapshot for today with loss
    snapshot = PnLSnapshot(
        portfolio_id=None,
        strategy_name=account,
        symbol="BTC-PERP",
        realized_pnl=Decimal("-1500"),
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=Decimal("-1500"),
        net_pnl=Decimal("-1500"),
        snapshot_ts=today_start + timedelta(hours=1),
    )
    db_session.add(snapshot)
    db_session.flush()
    
    engine = RiskEngine(_config(max_daily_loss=Decimal("-1000")))
    intent = _entry_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    assert result.passed is False
    assert result.reason == "max_daily_loss_exceeded"
    assert isinstance(result.risk_event, RiskEvent)
    assert result.risk_event.rule_name == "max_daily_loss_exceeded"


def test_max_daily_loss_allows_exit_intent_even_when_exceeded(db_session) -> None:
    """Exit intent (reduce_only=True) allowed even when daily loss exceeded."""
    account = "paper"
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Create a PnL snapshot for today with loss
    snapshot = PnLSnapshot(
        portfolio_id=None,
        strategy_name=account,
        symbol="BTC-PERP",
        realized_pnl=Decimal("-1500"),
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=Decimal("-1500"),
        net_pnl=Decimal("-1500"),
        snapshot_ts=today_start + timedelta(hours=1),
    )
    db_session.add(snapshot)
    db_session.flush()
    
    engine = RiskEngine(_config(max_daily_loss=Decimal("-1000")))
    intent = _exit_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    assert result.passed is True


def test_max_daily_loss_passes_when_loss_within_threshold(db_session) -> None:
    """Entry intent passes when today's loss is within threshold."""
    account = "paper"
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Create a PnL snapshot for today with acceptable loss
    snapshot = PnLSnapshot(
        portfolio_id=None,
        strategy_name=account,
        symbol="BTC-PERP",
        realized_pnl=Decimal("-500"),
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=Decimal("-500"),
        net_pnl=Decimal("-500"),
        snapshot_ts=today_start + timedelta(hours=1),
    )
    db_session.add(snapshot)
    db_session.flush()
    
    engine = RiskEngine(_config(max_daily_loss=Decimal("-1000")))
    intent = _entry_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    assert result.passed is True


def test_max_daily_loss_includes_funding_payments(db_session) -> None:
    """Max daily loss calculation includes funding payments."""
    account = "paper"
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Create a PnL snapshot for today
    snapshot = PnLSnapshot(
        portfolio_id=None,
        strategy_name=account,
        symbol="BTC-PERP",
        realized_pnl=Decimal("-300"),
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=Decimal("-300"),
        net_pnl=Decimal("-300"),
        snapshot_ts=today_start + timedelta(hours=1),
    )
    db_session.add(snapshot)
    
    # Create a funding payment for today
    funding = FundingPayment(
        exchange="binance",
        symbol="BTC-PERP",
        account_name=account,
        position_quantity=Decimal("1"),
        mark_price=Decimal("50000"),
        funding_rate=Decimal("0.0001"),
        payment_amount=Decimal("-800"),
        accrued_ts=today_start + timedelta(hours=2),
        created_ts=today_start + timedelta(hours=2),
    )
    db_session.add(funding)
    db_session.flush()
    
    engine = RiskEngine(_config(max_daily_loss=Decimal("-1000")))
    intent = _entry_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # -300 (realized) + -800 (funding) = -1100, which exceeds -1000 threshold
    assert result.passed is False
    assert result.reason == "max_daily_loss_exceeded"


def test_max_daily_loss_resets_at_utc_midnight(db_session) -> None:
    """Daily loss calculation respects UTC calendar day boundaries."""
    account = "paper"
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    
    # Create a large loss from yesterday
    old_snapshot = PnLSnapshot(
        portfolio_id=None,
        strategy_name=account,
        symbol="BTC-PERP",
        realized_pnl=Decimal("-2000"),
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=Decimal("-2000"),
        net_pnl=Decimal("-2000"),
        snapshot_ts=yesterday_start + timedelta(hours=12),
    )
    db_session.add(old_snapshot)
    
    # Create a small loss for today
    today_snapshot = PnLSnapshot(
        portfolio_id=None,
        strategy_name=account,
        symbol="BTC-PERP",
        realized_pnl=Decimal("-100"),
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=Decimal("-100"),
        net_pnl=Decimal("-100"),
        snapshot_ts=today_start + timedelta(hours=1),
    )
    db_session.add(today_snapshot)
    db_session.flush()
    
    engine = RiskEngine(_config(max_daily_loss=Decimal("-1000")))
    intent = _entry_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # Should only count today's loss (-100), not yesterday's (-2000)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Circuit breaker – reject condition
# ---------------------------------------------------------------------------

def test_circuit_breaker_triggers_on_n_consecutive_rejects(db_session) -> None:
    """Circuit breaker triggers when N consecutive rejects within window."""
    account = "paper"
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=300)
    
    # Create 5 rejected intents within the window
    for i in range(5):
        rejected_intent = OrderIntent(
            strategy_signal_id=None,
            portfolio_id=None,
            mode=account,
            exchange="binance",
            symbol="BTC-PERP",
            side="sell",
            order_type="market",
            time_in_force=None,
            quantity=Decimal("1"),
            limit_price=None,
            reduce_only=False,
            post_only=False,
            client_order_id=None,
            status="rejected",
            created_ts=window_start + timedelta(seconds=10 + i),
        )
        db_session.add(rejected_intent)
    db_session.flush()
    
    engine = RiskEngine(_config(
        circuit_breaker_max_rejects=5,
        circuit_breaker_active=True,
    ))
    intent = _entry_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # Circuit breaker is checked early (after stale_data), blocks all intents
    assert result.passed is False
    assert result.reason == "circuit_breaker_triggered"


# ---------------------------------------------------------------------------
# Circuit breaker – loss condition
# ---------------------------------------------------------------------------

def test_circuit_breaker_triggers_on_loss_within_window(db_session) -> None:
    """Circuit breaker triggers when loss exceeds threshold within window."""
    account = "paper"
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=300)
    
    # Create a loss-making snapshot within the window
    snapshot = PnLSnapshot(
        portfolio_id=None,
        strategy_name=account,
        symbol="BTC-PERP",
        realized_pnl=Decimal("-600"),
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=Decimal("-600"),
        net_pnl=Decimal("-600"),
        snapshot_ts=window_start + timedelta(seconds=100),
    )
    db_session.add(snapshot)
    db_session.flush()
    
    engine = RiskEngine(_config(
        circuit_breaker_loss_threshold=Decimal("-500"),
        circuit_breaker_active=True,
    ))
    intent = _entry_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # -600 < -500 threshold, so circuit breaker triggers
    assert result.passed is False
    assert result.reason == "circuit_breaker_triggered"


def test_circuit_breaker_blocks_reduce_only_intents(db_session) -> None:
    """Circuit breaker blocks exits (reduce_only=True) too."""
    account = "paper"
    
    engine = RiskEngine(_config(circuit_breaker_active=True))
    intent = _exit_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # Circuit breaker blocks all intents, including exits
    assert result.passed is False
    assert result.reason == "circuit_breaker_triggered"


def test_circuit_breaker_does_not_trigger_below_thresholds(db_session) -> None:
    """Circuit breaker does not trigger when conditions are not met."""
    account = "paper"
    
    engine = RiskEngine(_config(
        circuit_breaker_max_rejects=5,
        circuit_breaker_loss_threshold=Decimal("-500"),
        circuit_breaker_active=False,  # Not active
    ))
    intent = _entry_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # Circuit breaker not active, so intent should pass all checks
    assert result.passed is True


# ---------------------------------------------------------------------------
# Hedge leg mismatch detection
# ---------------------------------------------------------------------------

def test_hedge_leg_mismatch_blocks_when_spot_open_perp_missing(db_session) -> None:
    """Entry blocked when spot position exists but perp does not."""
    account = "paper"
    exchange = "binance"
    
    # Create an open spot position
    spot_position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-USD",
        instrument_type="spot",
        side="long",
        quantity=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=datetime.now(timezone.utc),
    )
    db_session.add(spot_position)
    db_session.flush()
    
    engine = RiskEngine(_config(spot_symbol="BTC-USD", perp_symbol="BTC-PERP"))
    intent = _entry_intent(mode=account, symbol="BTC-PERP")
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    assert result.passed is False
    assert result.reason == "hedge_leg_mismatch"


def test_hedge_leg_mismatch_blocks_when_perp_open_spot_missing(db_session) -> None:
    """Entry blocked when perp position exists but spot does not."""
    account = "paper"
    exchange = "binance"
    
    # Create an open perp position
    perp_position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-PERP",
        instrument_type="future",
        side="short",
        quantity=Decimal("2.0"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=Decimal("2"),
        margin_used=Decimal("100000"),
        snapshot_ts=datetime.now(timezone.utc),
    )
    db_session.add(perp_position)
    db_session.flush()
    
    engine = RiskEngine(_config(spot_symbol="BTC-USD", perp_symbol="BTC-PERP"))
    intent = _entry_intent(mode=account, symbol="BTC-USD")
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    assert result.passed is False
    assert result.reason == "hedge_leg_mismatch"


def test_hedge_leg_mismatch_passes_when_both_open(db_session) -> None:
    """No mismatch when both spot and perp legs are open."""
    account = "paper"
    exchange = "binance"
    
    # Create both spot and perp positions
    spot_position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-USD",
        instrument_type="spot",
        side="long",
        quantity=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=datetime.now(timezone.utc),
    )
    db_session.add(spot_position)
    
    perp_position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-PERP",
        instrument_type="future",
        side="short",
        quantity=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=Decimal("1"),
        margin_used=Decimal("75000"),
        snapshot_ts=datetime.now(timezone.utc),
    )
    db_session.add(perp_position)
    db_session.flush()
    
    engine = RiskEngine(_config(spot_symbol="BTC-USD", perp_symbol="BTC-PERP"))
    intent = _entry_intent(mode=account, symbol="BTC-PERP")
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    assert result.passed is True


def test_hedge_leg_mismatch_passes_when_both_closed(db_session) -> None:
    """No mismatch when both spot and perp legs are closed."""
    account = "paper"
    exchange = "binance"
    
    # No positions created; both are closed (qty=0)
    
    engine = RiskEngine(_config(spot_symbol="BTC-USD", perp_symbol="BTC-PERP"))
    intent = _entry_intent(mode=account, symbol="BTC-PERP")
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    assert result.passed is True


def test_hedge_leg_mismatch_does_not_apply_to_exit_intents(db_session) -> None:
    """Hedge leg mismatch check does not apply to exit intents."""
    account = "paper"
    exchange = "binance"
    
    # Create an open spot position but no perp position
    spot_position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-USD",
        instrument_type="spot",
        side="long",
        quantity=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=datetime.now(timezone.utc),
    )
    db_session.add(spot_position)
    db_session.flush()
    
    engine = RiskEngine(_config(spot_symbol="BTC-USD", perp_symbol="BTC-PERP"))
    intent = _exit_intent(mode=account, symbol="BTC-PERP")
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # Even with a mismatch, exit intents bypass this check
    assert result.passed is True


def test_hedge_leg_mismatch_skipped_when_symbols_not_configured(db_session) -> None:
    """Mismatch check is skipped if spot/perp symbols are not configured."""
    account = "paper"
    exchange = "binance"
    
    # Create an open spot position but no perp position
    spot_position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-USD",
        instrument_type="spot",
        side="long",
        quantity=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=datetime.now(timezone.utc),
    )
    db_session.add(spot_position)
    db_session.flush()
    
    # Create config without spot/perp symbols
    engine = RiskEngine(_config(spot_symbol="", perp_symbol=""))
    intent = _entry_intent(mode=account, symbol="BTC-PERP")
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # Check should pass because symbols are not configured
    assert result.passed is True


# ---------------------------------------------------------------------------
# Emergency flatten
# ---------------------------------------------------------------------------

def test_emergency_flatten_creates_closing_intents_for_all_open_positions(db_session) -> None:
    """emergency_flatten creates a closing intent for each open position."""
    account = "paper"
    exchange = "binance"
    now = datetime.now(timezone.utc)
    
    # Create multiple open positions
    spot_position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-USD",
        instrument_type="spot",
        side="long",
        quantity=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=now,
    )
    db_session.add(spot_position)
    
    perp_position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-PERP",
        instrument_type="future",
        side="short",
        quantity=Decimal("2.0"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=Decimal("2"),
        margin_used=Decimal("100000"),
        snapshot_ts=now,
    )
    db_session.add(perp_position)
    db_session.flush()
    
    engine = RiskEngine(_config())
    closing_intents = engine.emergency_flatten(
        session=db_session,
        account_name=account,
        exchange=exchange,
        spot_symbol="BTC-USD",
        perp_symbol="BTC-PERP",
    )
    
    assert len(closing_intents) == 2
    
    # Find the intents by symbol
    spot_close = next(i for i in closing_intents if i.symbol == "BTC-USD")
    perp_close = next(i for i in closing_intents if i.symbol == "BTC-PERP")
    
    # Check spot closing intent (long position -> sell to close)
    assert spot_close.mode == account
    assert spot_close.exchange == exchange
    assert spot_close.reduce_only is True
    assert spot_close.order_type == "market"
    assert spot_close.status == "pending"
    assert spot_close.quantity == Decimal("1.5")
    assert spot_close.side == "sell"  # Long position closes with sell
    
    # Check perp closing intent (short position -> buy to close)
    assert perp_close.mode == account
    assert perp_close.exchange == exchange
    assert perp_close.reduce_only is True
    assert perp_close.order_type == "market"
    assert perp_close.status == "pending"
    assert perp_close.quantity == Decimal("2.0")
    assert perp_close.side == "buy"  # Short position closes with buy


def test_emergency_flatten_returns_empty_list_when_no_open_positions(db_session) -> None:
    """emergency_flatten returns empty list when no open positions exist."""
    account = "paper"
    exchange = "binance"
    
    engine = RiskEngine(_config())
    closing_intents = engine.emergency_flatten(
        session=db_session,
        account_name=account,
        exchange=exchange,
        spot_symbol="BTC-USD",
        perp_symbol="BTC-PERP",
    )
    
    assert len(closing_intents) == 0
    assert closing_intents == []


def test_emergency_flatten_persists_one_risk_event(db_session) -> None:
    """emergency_flatten persists one RiskEvent with alert severity."""
    account = "paper"
    exchange = "binance"
    now = datetime.now(timezone.utc)
    
    # Create one open position
    position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-USD",
        instrument_type="spot",
        side="long",
        quantity=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=now,
    )
    db_session.add(position)
    db_session.flush()
    
    engine = RiskEngine(_config())
    closing_intents = engine.emergency_flatten(
        session=db_session,
        account_name=account,
        exchange=exchange,
        spot_symbol="BTC-USD",
        perp_symbol="BTC-PERP",
    )
    
    # Check that a RiskEvent was added to the session
    # (Note: we can't directly query it without flushing, but we can check the session)
    risk_events = [obj for obj in db_session.new if isinstance(obj, RiskEvent)]
    
    assert len(closing_intents) == 1
    assert len(risk_events) == 1
    
    event = risk_events[0]
    assert event.event_type == "alert"
    assert event.severity == "critical"
    assert event.rule_name == "emergency_flatten"
    assert event.strategy_name == account
    assert event.details_json["positions_closed"] == 1


def test_emergency_flatten_closing_side_for_long_position(db_session) -> None:
    """Closing side for a long position is 'sell'."""
    account = "paper"
    exchange = "binance"
    now = datetime.now(timezone.utc)
    
    position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-USD",
        instrument_type="spot",
        side="long",  # Explicitly long
        quantity=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=now,
    )
    db_session.add(position)
    db_session.flush()
    
    engine = RiskEngine(_config())
    closing_intents = engine.emergency_flatten(
        session=db_session,
        account_name=account,
        exchange=exchange,
    )
    
    assert len(closing_intents) == 1
    assert closing_intents[0].side == "sell"


def test_emergency_flatten_closing_side_for_short_position(db_session) -> None:
    """Closing side for a short position is 'buy'."""
    account = "paper"
    exchange = "binance"
    now = datetime.now(timezone.utc)
    
    position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-PERP",
        instrument_type="future",
        side="short",  # Explicitly short
        quantity=Decimal("2.0"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=Decimal("2"),
        margin_used=Decimal("100000"),
        snapshot_ts=now,
    )
    db_session.add(position)
    db_session.flush()
    
    engine = RiskEngine(_config())
    closing_intents = engine.emergency_flatten(
        session=db_session,
        account_name=account,
        exchange=exchange,
    )
    
    assert len(closing_intents) == 1
    assert closing_intents[0].side == "buy"


# ---------------------------------------------------------------------------
# Check order verification
# ---------------------------------------------------------------------------

def test_circuit_breaker_checked_before_funding_edge(db_session) -> None:
    """Circuit breaker is checked before funding edge."""
    account = "paper"
    
    engine = RiskEngine(_config(
        circuit_breaker_active=True,
        min_entry_funding_rate=Decimal("0.001"),  # High threshold
    ))
    intent = _entry_intent(mode=account)
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=Decimal("0.0001"),  # Below threshold
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # Should fail on circuit_breaker, not funding_edge
    assert result.reason == "circuit_breaker_triggered"


def test_max_daily_loss_checked_before_max_notional(db_session) -> None:
    """Max daily loss is checked before max notional."""
    account = "paper"
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Create a large loss for today
    snapshot = PnLSnapshot(
        portfolio_id=None,
        strategy_name=account,
        symbol="BTC-PERP",
        realized_pnl=Decimal("-1500"),
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=Decimal("-1500"),
        net_pnl=Decimal("-1500"),
        snapshot_ts=today_start + timedelta(hours=1),
    )
    db_session.add(snapshot)
    db_session.flush()
    
    engine = RiskEngine(_config(
        max_daily_loss=Decimal("-1000"),
        max_notional_per_symbol=Decimal("1000"),  # Would be exceeded
    ))
    intent = _entry_intent(mode=account, qty="100")
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # Should fail on max_daily_loss, not max_notional
    assert result.reason == "max_daily_loss_exceeded"


def test_hedge_leg_mismatch_checked_after_max_notional(db_session) -> None:
    """Hedge leg mismatch is checked last (after max_notional)."""
    account = "paper"
    exchange = "binance"
    
    # Create a mismatch (spot open, perp closed)
    spot_position = PositionSnapshot(
        exchange=exchange,
        account_name=account,
        symbol="BTC-USD",
        instrument_type="spot",
        side="long",
        quantity=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=datetime.now(timezone.utc),
    )
    db_session.add(spot_position)
    db_session.flush()
    
    engine = RiskEngine(_config(
        spot_symbol="BTC-USD",
        perp_symbol="BTC-PERP",
        max_notional_per_symbol=Decimal("1000"),
    ))
    intent = _entry_intent(mode=account, qty="100")
    
    result = engine.check(
        session=db_session,
        order_intent=intent,
        funding_rate=_RATE_ABOVE,
        mark_price=_MARK,
        latest_funding_ts=_fresh_ts(),
    )
    
    # Should fail on max_notional first, before hedge_leg_mismatch
    assert result.reason == "max_notional_exceeded"
