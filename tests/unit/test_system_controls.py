from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from apps.paper_trader.main import _paper_mm_control_gate
from apps.strategy_engine.delta_neutral_runner import DeltaNeutralRunner
from core.risk.risk_engine import RiskCheckResult


class _Result:
    def __init__(self, *, first=None):
        self._first = first

    def scalars(self):
        return self

    def first(self):
        return self._first


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


def _make_runner(session: Mock, account_name: str = "paper_dn") -> DeltaNeutralRunner:
    return DeltaNeutralRunner(
        session_factory=lambda: _SessionCtx(session),
        settings=_settings(),
        account_name=account_name,
    )


def test_kill_switch_blocks_dn_iteration(monkeypatch) -> None:
    session = Mock()
    runner = _make_runner(session, account_name="paper_dn")

    evaluate_mock = Mock()
    runner._strategy.evaluate = evaluate_mock  # type: ignore[method-assign]
    runner._latest_perp_qty = lambda **_kwargs: Decimal("0")  # type: ignore[method-assign]
    runner._latest_spot_qty = lambda **_kwargs: Decimal("0")  # type: ignore[method-assign]

    events: list[str] = []

    def _capture(event, **_kwargs):
        events.append(event)

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_kill_switch_active", lambda _db: True)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_strategy_enabled", lambda _db, _s: True)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner._log.warning", _capture)

    runner._run_iteration(session=session, account_name="paper_dn")

    assert evaluate_mock.call_count == 0
    assert "kill_switch_active_halting_dn" in events


def test_kill_switch_triggers_dn_flatten(monkeypatch) -> None:
    session = Mock()
    runner = _make_runner(session, account_name="paper_dn")

    flatten_mock = AsyncMock()
    runner.emergency_flatten = flatten_mock  # type: ignore[method-assign]
    runner._latest_perp_qty = lambda **_kwargs: Decimal("0.8")  # type: ignore[method-assign]
    runner._latest_spot_qty = lambda **_kwargs: Decimal("0.8")  # type: ignore[method-assign]

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_kill_switch_active", lambda _db: True)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_strategy_enabled", lambda _db, _s: True)

    runner._run_iteration(session=session, account_name="paper_dn")

    flatten_mock.assert_awaited_once_with(reason="kill_switch")


def test_kill_switch_blocks_mm_quoting(monkeypatch) -> None:
    session = Mock()
    logger = Mock()
    place_orders = Mock()

    monkeypatch.setattr("apps.paper_trader.main.is_kill_switch_active", lambda _db: True)
    monkeypatch.setattr("apps.paper_trader.main.is_strategy_enabled", lambda _db, _s: True)

    should_skip = _paper_mm_control_gate(session=session, logger=logger, iteration=1)
    if not should_skip:
        place_orders()

    assert should_skip is True
    place_orders.assert_not_called()
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args[0] == "kill_switch_active_halting_mm"


def test_dn_disabled_blocks_entry_preserves_position(monkeypatch) -> None:
    session = Mock()
    runner = _make_runner(session, account_name="paper_dn")

    flatten_mock = AsyncMock()
    runner.emergency_flatten = flatten_mock  # type: ignore[method-assign]
    evaluate_mock = Mock()
    runner._strategy.evaluate = evaluate_mock  # type: ignore[method-assign]

    events: list[str] = []

    def _capture(event, **_kwargs):
        events.append(event)

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_kill_switch_active", lambda _db: False)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_strategy_enabled", lambda _db, _s: False)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner._log.warning", _capture)

    runner._run_iteration(session=session, account_name="paper_dn")

    assert "dn_strategy_disabled_skipping" in events
    assert evaluate_mock.call_count == 0
    flatten_mock.assert_not_awaited()


def test_kill_switch_inactive_allows_normal_operation(monkeypatch) -> None:
    session = Mock()
    runner = _make_runner(session, account_name="paper_dn")

    now_utc = datetime.now(timezone.utc)
    tick = Mock(event_ts=now_utc - timedelta(seconds=5), mid_price=Decimal("2500"))
    spot_tick = Mock(event_ts=now_utc - timedelta(seconds=5), mid_price=Decimal("2500"))
    funding = Mock(funding_rate=Decimal("0.0001"), funding_interval_hours=1)

    # command row, latest perp tick, latest spot tick, latest funding
    session.execute.side_effect = [
        _Result(first=None),
        _Result(first=tick),
        _Result(first=spot_tick),
        _Result(first=funding),
    ]

    preflight_mock = Mock(return_value=RiskCheckResult(passed=True))
    runner.risk_engine.run_preflight = preflight_mock  # type: ignore[method-assign]
    runner._check_daily_loss = lambda _db: False  # type: ignore[method-assign]
    runner._current_position_state = lambda **_kwargs: {"has_spot": False, "has_perp": False}  # type: ignore[method-assign]
    signal = Mock(signal_type="BLOCKED")
    evaluate_mock = Mock(return_value=signal)
    runner._strategy.evaluate = evaluate_mock  # type: ignore[method-assign]

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_kill_switch_active", lambda _db: False)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_strategy_enabled", lambda _db, _s: True)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.compute_hedge_ratio", lambda *_args, **_kwargs: SimpleNamespace(
        spot_notional=Decimal("0"),
        perp_notional=Decimal("0"),
        hedge_ratio=Decimal("1"),
        spot_qty=Decimal("0"),
        perp_qty=Decimal("0"),
        mark_price=Decimal("2500"),
        is_balanced=True,
    ))

    runner._run_iteration(session=session, account_name="paper_dn")

    preflight_mock.assert_called_once()
    assert evaluate_mock.call_count == 1

    mm_session = Mock()
    mm_logger = Mock()
    monkeypatch.setattr("apps.paper_trader.main.is_kill_switch_active", lambda _db: False)
    monkeypatch.setattr("apps.paper_trader.main.is_strategy_enabled", lambda _db, _s: True)
    assert _paper_mm_control_gate(session=mm_session, logger=mm_logger, iteration=1) is False
