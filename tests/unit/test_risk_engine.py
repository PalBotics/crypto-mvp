from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

from core.models.order_intent import OrderIntent
from core.models.risk_event import RiskEvent
from core.risk.engine import RiskCheckResult, RiskConfig, RiskEngine
from core.risk.risk_engine import RiskEngine as SharedRiskEngine


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


class _SharedResult:
    def __init__(self, *, first=None, all_rows=None):
        self._first = first
        self._all_rows = all_rows if all_rows is not None else []

    def scalars(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all_rows


def _shared_engine(session: Mock) -> SharedRiskEngine:
    engine = SharedRiskEngine(account_name="paper_dn", db=session)
    engine.risk_max_notional_usd = Decimal("5000")
    engine.risk_max_symbol_notional_usd = Decimal("3000")
    return engine


def test_max_notional_blocks_entry() -> None:
    session = Mock()
    pos = Mock(quantity=Decimal("2"), mark_price=Decimal("2400"), avg_entry_price=Decimal("2400"))
    session.execute.return_value = _SharedResult(all_rows=[pos])

    engine = _shared_engine(session)
    result = engine.check_max_notional(
        account_name="paper_dn",
        proposed_additional_usd=Decimal("300"),
    )

    assert result.passed is False
    assert result.reason == "max_notional_exceeded"
    persisted = [c.args[0] for c in session.add.call_args_list if c.args and isinstance(c.args[0], RiskEvent)]
    assert any(evt.event_type == "max_notional_exceeded" for evt in persisted)


def test_max_notional_passes_under_limit() -> None:
    session = Mock()
    pos = Mock(quantity=Decimal("1"), mark_price=Decimal("1000"), avg_entry_price=Decimal("1000"))
    session.execute.return_value = _SharedResult(all_rows=[pos])

    engine = _shared_engine(session)
    result = engine.check_max_notional(
        account_name="paper_dn",
        proposed_additional_usd=Decimal("500"),
    )

    assert result.passed is True


def test_max_symbol_blocks_entry() -> None:
    session = Mock()
    pos = Mock(quantity=Decimal("1"), mark_price=Decimal("2900"), avg_entry_price=Decimal("2900"))
    session.execute.return_value = _SharedResult(all_rows=[pos])

    engine = _shared_engine(session)
    result = engine.check_max_symbol_notional(
        symbol="ETHUSD",
        proposed_additional_usd=Decimal("200"),
    )

    assert result.passed is False
    assert result.reason == "max_symbol_notional_exceeded"


def test_stale_data_blocks_iteration() -> None:
    session = Mock()
    tick = Mock(event_ts=datetime.now(timezone.utc) - timedelta(seconds=200))
    session.execute.return_value = _SharedResult(first=tick)

    engine = _shared_engine(session)
    result = engine.check_data_freshness(exchange="coinbase_advanced", symbol="ETH-PERP")

    assert result.passed is False
    assert result.reason == "stale_feed"
    persisted = [c.args[0] for c in session.add.call_args_list if c.args and isinstance(c.args[0], RiskEvent)]
    assert any(evt.event_type == "stale_feed" for evt in persisted)


def test_stale_data_passes_fresh_data() -> None:
    session = Mock()
    tick = Mock(event_ts=datetime.now(timezone.utc) - timedelta(seconds=5))
    session.execute.return_value = _SharedResult(first=tick)

    engine = _shared_engine(session)
    result = engine.check_data_freshness(exchange="coinbase_advanced", symbol="ETH-PERP")

    assert result.passed is True


def test_risk_engine_passes_clean_state() -> None:
    session = Mock()
    fresh_tick = Mock(event_ts=datetime.now(timezone.utc) - timedelta(seconds=5))
    session.execute.side_effect = [
        _SharedResult(first=fresh_tick),
        _SharedResult(all_rows=[]),
        _SharedResult(all_rows=[]),
    ]

    engine = _shared_engine(session)
    result = engine.run_preflight(
        exchanges_to_check=[("coinbase_advanced", "ETH-PERP")],
        proposed_notional_usd=Decimal("500"),
        proposed_symbol="ETHUSD",
    )

    assert result.passed is True
    persisted = [c.args[0] for c in session.add.call_args_list if c.args and isinstance(c.args[0], RiskEvent)]
    assert persisted == []


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
