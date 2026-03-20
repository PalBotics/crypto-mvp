from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from apps.strategy_engine import delta_neutral_runner as dn_runner_module
from apps.strategy_engine.delta_neutral_runner import DeltaNeutralRunner
from core.models.risk_event import RiskEvent
from core.strategy.delta_neutral import DeltaNeutralConfig, DeltaNeutralStrategy


class _Result:
    def __init__(self, *, first=None, all_rows=None, scalar=None):
        self._first = first
        self._all_rows = all_rows if all_rows is not None else []
        self._scalar = scalar

    def scalars(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all_rows

    def scalar_one(self):
        return self._scalar


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False


def _settings(**overrides):
    base = {
        "dn_funding_entry_threshold_apr": 5.0,
        "dn_funding_exit_threshold_apr": 2.0,
        "dn_force_entry": False,
        "dn_block_on_ratio_violation": True,
        "run_mode": "paper",
        "dn_iteration_seconds": 60,
        "dn_contract_qty": 8,
        "dn_spot_exchange": "kraken",
        "dn_spot_symbol": "ETHUSD",
        "dn_perp_exchange": "coinbase_advanced",
        "dn_perp_symbol": "ETH-PERP",
        "dn_max_daily_loss_usd": 50.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_runner(*, session, account_name: str = "paper_dn") -> DeltaNeutralRunner:
    runner = DeltaNeutralRunner(
        session_factory=lambda: _SessionCtx(session),
        settings=_settings(),
        account_name=account_name,
    )
    return runner


def test_hedge_ratio_violation_blocks_new_entry() -> None:
    strategy = DeltaNeutralStrategy(
        DeltaNeutralConfig(
            entry_threshold_apr=Decimal("5.0"),
            exit_threshold_apr=Decimal("2.0"),
            block_on_ratio_violation=True,
            run_mode="paper",
        )
    )
    db = Mock()

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("7.0"),
        current_position={"has_spot": True, "has_perp": True},
        hedge_status={"is_balanced": False, "hedge_ratio": Decimal("1.5")},
        db=db,
    )

    assert signal.signal_type == "BLOCKED"
    risk_events = [
        call.args[0]
        for call in db.add.call_args_list
        if call.args and isinstance(call.args[0], RiskEvent)
    ]
    assert any(evt.event_type == "hedge_ratio_violation" for evt in risk_events)


def test_hedge_ratio_violation_disabled_by_config() -> None:
    strategy = DeltaNeutralStrategy(
        DeltaNeutralConfig(
            entry_threshold_apr=Decimal("5.0"),
            exit_threshold_apr=Decimal("2.0"),
            block_on_ratio_violation=False,
            run_mode="paper",
        )
    )
    db = Mock()

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("7.0"),
        current_position={"has_spot": True, "has_perp": True},
        hedge_status={"is_balanced": False, "hedge_ratio": Decimal("1.5")},
        db=db,
    )

    assert signal.signal_type == "REBALANCE"


def test_stale_feed_skips_iteration(monkeypatch) -> None:
    session = Mock()
    stale_tick = Mock()
    stale_tick.event_ts = datetime.now(timezone.utc) - timedelta(seconds=200)
    stale_tick.mid_price = Decimal("2300")
    # First query checks dn_runner_commands; second query reads latest perp tick.
    session.execute.side_effect = [
        _Result(first=None),
        _Result(first=stale_tick),
    ]

    runner = _make_runner(session=session, account_name="paper_dn_stale")
    evaluate_mock = Mock()
    runner._strategy.evaluate = evaluate_mock  # type: ignore[method-assign]

    log_events: list[str] = []

    def _capture(event, **_kwargs):
        log_events.append(event)

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner._log.warning", _capture)

    runner._run_iteration(session=session, account_name="paper_dn_stale")

    assert evaluate_mock.call_count == 0
    risk_events = [
        call.args[0]
        for call in session.add.call_args_list
        if call.args and isinstance(call.args[0], RiskEvent)
    ]
    assert any(evt.event_type == "stale_feed" for evt in risk_events)
    runner.close()


def test_daily_loss_triggers_flatten(monkeypatch) -> None:
    iteration_session = Mock()
    emergency_session = Mock()

    runner = DeltaNeutralRunner(
        session_factory=lambda: _SessionCtx(emergency_session),
        settings=_settings(dn_max_daily_loss_usd=50.0),
        account_name="paper_dn_loss",
    )

    runner._latest_mark_price = lambda _db: Decimal("2400")  # type: ignore[method-assign]
    runner._latest_perp_qty = lambda **_kwargs: Decimal("0")  # type: ignore[method-assign]
    runner._latest_spot_qty = lambda **_kwargs: Decimal("0")  # type: ignore[method-assign]

    spot_position = Mock()
    spot_position.exchange = "kraken"
    spot_position.symbol = "ETHUSD"
    spot_position.side = "long"
    spot_position.quantity = Decimal("0.8")
    spot_position.avg_entry_price = Decimal("2500")

    iteration_session.execute.side_effect = [
        _Result(scalar=Decimal("0")),
        _Result(all_rows=[spot_position]),
    ]

    log_events: list[str] = []

    def _capture(event, **_kwargs):
        log_events.append(event)

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner._log.error", _capture)

    breached = runner._check_daily_loss(iteration_session)

    assert breached is True
    assert "dn_max_daily_loss_breached" in log_events
    risk_events = [
        call.args[0]
        for call in emergency_session.add.call_args_list
        if call.args and isinstance(call.args[0], RiskEvent)
    ]
    assert any(evt.event_type == "emergency_flatten" and evt.severity == "critical" for evt in risk_events)
    runner.close()


def test_emergency_flatten_closes_both_legs(monkeypatch) -> None:
    session = Mock()
    runner = _make_runner(session=session, account_name="paper_dn_flatten")

    runner._latest_mark_price = lambda _db: Decimal("2400")  # type: ignore[method-assign]
    runner._latest_perp_qty = lambda **_kwargs: Decimal("0.8")  # type: ignore[method-assign]
    runner._latest_spot_qty = lambda **_kwargs: Decimal("0.8")  # type: ignore[method-assign]

    close_mock = Mock(return_value=Decimal("0"))
    spot_sell_mock = Mock()
    monkeypatch.setattr(dn_runner_module, "close_perp_short", close_mock)
    runner._simulate_spot_fill = spot_sell_mock  # type: ignore[method-assign]

    events: list[str] = []

    def _capture(event, **_kwargs):
        events.append(event)

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner._log.critical", _capture)

    asyncio.run(runner.emergency_flatten(reason="test"))

    assert close_mock.call_count == 1
    assert spot_sell_mock.call_count == 1
    assert events.count("dn_emergency_flatten_executed") == 1
    assert runner._flattened is True
    risk_events = [
        call.args[0]
        for call in session.add.call_args_list
        if call.args and isinstance(call.args[0], RiskEvent)
    ]
    assert any(evt.event_type == "emergency_flatten" and evt.severity == "critical" for evt in risk_events)
    runner.close()


def test_flatten_blocks_all_subsequent_signals() -> None:
    strategy = DeltaNeutralStrategy(
        DeltaNeutralConfig(
            entry_threshold_apr=Decimal("5.0"),
            exit_threshold_apr=Decimal("2.0"),
            force_entry=True,
            run_mode="paper",
        )
    )
    strategy.set_flattened(True)

    db = Mock()
    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("20.0"),
        current_position=None,
        hedge_status={"is_balanced": True},
        db=db,
    )

    assert signal.signal_type == "BLOCKED"


def test_emergency_flatten_atomic_spot_skipped_if_perp_fails(monkeypatch) -> None:
    session = Mock()
    runner = _make_runner(session=session, account_name="paper_dn_atomic")

    runner._latest_mark_price = lambda _db: Decimal("2400")  # type: ignore[method-assign]
    runner._latest_perp_qty = lambda **_kwargs: Decimal("0.8")  # type: ignore[method-assign]
    runner._latest_spot_qty = lambda **_kwargs: Decimal("0.8")  # type: ignore[method-assign]

    def _raise(*_args, **_kwargs):
        raise RuntimeError("perp close failed")

    monkeypatch.setattr(dn_runner_module, "close_perp_short", _raise)
    spot_sell_mock = Mock()
    runner._simulate_spot_fill = spot_sell_mock  # type: ignore[method-assign]

    logged_errors: list[str] = []

    def _capture_error(event, **_kwargs):
        logged_errors.append(event)

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner._log.error", _capture_error)

    asyncio.run(runner.emergency_flatten(reason="test_atomic"))

    assert spot_sell_mock.call_count == 0
    assert "dn_emergency_flatten_perp_failed" in logged_errors
    assert runner._flattened is True
    runner.close()
