from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from apps.strategy_engine.delta_neutral_runner import DeltaNeutralRunner
from core.models.fill_record import FillRecord
from core.models.strategy_signal_log import StrategySignalLog
from scripts.check_live_entry_conditions import EntryCheckState, evaluate_conditions


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
        "live_dn_contract_qty": 2,
        "dn_spot_exchange": "kraken",
        "dn_spot_symbol": "ETHUSD",
        "dn_perp_exchange": "coinbase_advanced",
        "dn_perp_symbol": "ETH-PERP",
        "dn_max_daily_loss_usd": 50.0,
        "live_mode": False,
        "dry_run": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _runner(session, **setting_overrides) -> DeltaNeutralRunner:
    return DeltaNeutralRunner(
        session_factory=lambda: _SessionCtx(session),
        settings=_settings(**setting_overrides),
        account_name="paper_dn",
    )


def _prepare_runner_for_iteration(runner: DeltaNeutralRunner) -> None:
    runner.risk_engine.run_preflight = Mock(return_value=SimpleNamespace(passed=True))  # type: ignore[method-assign]
    runner._check_daily_loss = lambda _db: False  # type: ignore[method-assign]
    runner._current_position_state = lambda **_kwargs: {"has_spot": False, "has_perp": False}  # type: ignore[method-assign]


def test_dry_run_iteration_summary_logged(monkeypatch) -> None:
    session = Mock()
    now_utc = datetime.now(timezone.utc)
    tick = Mock(event_ts=now_utc - timedelta(seconds=5), mid_price=Decimal("2127"))
    spot_tick = Mock(event_ts=now_utc - timedelta(seconds=5), mid_price=Decimal("2127"))
    funding = Mock(funding_rate=Decimal("-0.0002"), funding_interval_hours=1)

    session.execute.side_effect = [
        _Result(first=None),
        _Result(first=tick),
        _Result(first=spot_tick),
        _Result(first=funding),
    ]

    runner = _runner(session, live_mode=True, dry_run=True)
    _prepare_runner_for_iteration(runner)

    events: list[tuple[str, dict]] = []

    def _capture(event, **kwargs):
        events.append((event, kwargs))

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_kill_switch_active", lambda _db: False)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_strategy_enabled", lambda _db, _s: True)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.compute_hedge_ratio", lambda *_args, **_kwargs: SimpleNamespace(
        spot_notional=Decimal("0"),
        perp_notional=Decimal("0"),
        hedge_ratio=Decimal("1"),
        spot_qty=Decimal("0"),
        perp_qty=Decimal("0"),
        mark_price=Decimal("2127"),
        is_balanced=True,
    ))
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner._log.info", _capture)

    runner._run_iteration(session=session, account_name="paper_dn")

    dry_run_events = [kwargs for event, kwargs in events if event == "dry_run_iteration_summary"]
    assert len(dry_run_events) == 1
    summary = dry_run_events[0]
    assert summary["signal"] == "BLOCKED"
    assert summary["would_enter"] is False


def test_dry_run_does_not_persist_fills(monkeypatch) -> None:
    session = Mock()
    now_utc = datetime.now(timezone.utc)
    tick = Mock(event_ts=now_utc - timedelta(seconds=5), mid_price=Decimal("2127"))
    spot_tick = Mock(event_ts=now_utc - timedelta(seconds=5), mid_price=Decimal("2127"))
    funding = Mock(funding_rate=Decimal("0.001"), funding_interval_hours=1)

    session.execute.side_effect = [
        _Result(first=None),
        _Result(first=tick),
        _Result(first=spot_tick),
        _Result(first=funding),
    ]

    runner = _runner(session, live_mode=True, dry_run=True, dn_force_entry=True)
    _prepare_runner_for_iteration(runner)

    open_perp_mock = Mock()
    simulate_spot_mock = Mock()

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_kill_switch_active", lambda _db: False)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_strategy_enabled", lambda _db, _s: True)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.open_perp_short", open_perp_mock)
    runner._simulate_spot_fill = simulate_spot_mock  # type: ignore[method-assign]
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.compute_hedge_ratio", lambda *_args, **_kwargs: SimpleNamespace(
        spot_notional=Decimal("0"),
        perp_notional=Decimal("0"),
        hedge_ratio=Decimal("1"),
        spot_qty=Decimal("0"),
        perp_qty=Decimal("0"),
        mark_price=Decimal("2127"),
        is_balanced=True,
    ))

    runner._run_iteration(session=session, account_name="paper_dn")

    open_perp_mock.assert_not_called()
    simulate_spot_mock.assert_not_called()
    added_models = [call.args[0] for call in session.add.call_args_list if call.args]
    assert not any(isinstance(item, FillRecord) for item in added_models)


def test_signal_log_persisted_in_paper_mode(monkeypatch) -> None:
    session = Mock()
    now_utc = datetime.now(timezone.utc)
    tick = Mock(event_ts=now_utc - timedelta(seconds=5), mid_price=Decimal("2127"))
    spot_tick = Mock(event_ts=now_utc - timedelta(seconds=5), mid_price=Decimal("2127"))
    funding = Mock(funding_rate=Decimal("-0.0002"), funding_interval_hours=1)

    session.execute.side_effect = [
        _Result(first=None),
        _Result(first=tick),
        _Result(first=spot_tick),
        _Result(first=funding),
    ]

    runner = _runner(session, live_mode=False, dry_run=False)
    _prepare_runner_for_iteration(runner)

    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_kill_switch_active", lambda _db: False)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.is_strategy_enabled", lambda _db, _s: True)
    monkeypatch.setattr("apps.strategy_engine.delta_neutral_runner.compute_hedge_ratio", lambda *_args, **_kwargs: SimpleNamespace(
        spot_notional=Decimal("0"),
        perp_notional=Decimal("0"),
        hedge_ratio=Decimal("1"),
        spot_qty=Decimal("0"),
        perp_qty=Decimal("0"),
        mark_price=Decimal("2127"),
        is_balanced=True,
    ))

    runner._run_iteration(session=session, account_name="paper_dn")

    added_models = [call.args[0] for call in session.add.call_args_list if call.args]
    logs = [item for item in added_models if isinstance(item, StrategySignalLog)]
    assert len(logs) == 1
    assert logs[0].is_dry_run is False


def test_entry_conditions_funding_check() -> None:
    state = EntryCheckState(
        live_mode=True,
        kill_switch_inactive=True,
        funding_apr=Decimal("3.0"),
        funding_threshold_apr=Decimal("5.0"),
        kraken_age_seconds=5,
        coinbase_age_seconds=5,
        positions_flat=True,
        credentials_set=True,
        feeds_match=True,
        daily_loss_usd=Decimal("0"),
        live_dn_contract_qty=2,
    )

    results = evaluate_conditions(state)
    funding_result = next(r for r in results if r.name == "Funding APR threshold")
    assert funding_result.passed is False


def test_entry_conditions_all_pass() -> None:
    state = EntryCheckState(
        live_mode=True,
        kill_switch_inactive=True,
        funding_apr=Decimal("8.0"),
        funding_threshold_apr=Decimal("5.0"),
        kraken_age_seconds=4,
        coinbase_age_seconds=2,
        positions_flat=True,
        credentials_set=True,
        feeds_match=True,
        daily_loss_usd=Decimal("0"),
        live_dn_contract_qty=2,
    )

    results = evaluate_conditions(state)
    assert all(r.passed for r in results)
