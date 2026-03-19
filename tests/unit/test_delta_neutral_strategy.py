from decimal import Decimal
from unittest.mock import Mock

from core.strategy.delta_neutral import DeltaNeutralConfig, DeltaNeutralStrategy


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def all(self):
        return self._value


def _strategy(*, force_entry: bool = False, block_on_ratio_violation: bool = True) -> DeltaNeutralStrategy:
    return DeltaNeutralStrategy(
        DeltaNeutralConfig(
            entry_threshold_apr=Decimal("5.0"),
            exit_threshold_apr=Decimal("2.0"),
            force_entry=force_entry,
            block_on_ratio_violation=block_on_ratio_violation,
            run_mode="paper",
        )
    )


def test_entry_blocked_when_funding_negative(monkeypatch) -> None:
    events: list[tuple[str, dict]] = []

    def _capture(name: str):
        def _inner(event, **kwargs):
            events.append((event, kwargs))
        return _inner

    monkeypatch.setattr("core.strategy.delta_neutral._log.info", _capture("info"))

    strategy = _strategy()
    db = Mock()

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("-0.88"),
        current_position=None,
        hedge_status={"is_balanced": False},
        db=db,
    )

    assert signal.signal_type == "BLOCKED"
    assert any(evt == "entry_blocked_funding_below_threshold" for evt, _ in events)


def test_entry_blocked_when_funding_below_threshold() -> None:
    strategy = _strategy()
    db = Mock()

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("3.5"),
        current_position=None,
        hedge_status={"is_balanced": True},
        db=db,
    )

    assert signal.signal_type == "BLOCKED"


def test_entry_triggered_when_funding_above_threshold() -> None:
    strategy = _strategy()
    db = Mock()

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("8.0"),
        current_position=None,
        hedge_status={"is_balanced": True},
        db=db,
    )

    assert signal.signal_type == "ENTER"


def test_exit_triggered_when_funding_drops_below_exit_threshold(monkeypatch) -> None:
    events: list[tuple[str, dict]] = []

    def _capture(event, **kwargs):
        events.append((event, kwargs))

    monkeypatch.setattr("core.strategy.delta_neutral._log.info", _capture)

    strategy = _strategy()
    db = Mock()

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("1.5"),
        current_position={"has_spot": True, "has_perp": True},
        hedge_status={"is_balanced": True},
        db=db,
    )

    assert signal.signal_type == "EXIT"
    assert any(evt == "exit_triggered_low_funding" for evt, _ in events)


def test_hold_when_position_open_and_balanced() -> None:
    strategy = _strategy()
    db = Mock()

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("7.0"),
        current_position={"has_spot": True, "has_perp": True},
        hedge_status={"is_balanced": True, "hedge_ratio": Decimal("1.0")},
        db=db,
    )

    assert signal.signal_type == "HOLD"


def test_rebalance_when_ratio_drifts() -> None:
    strategy = _strategy(block_on_ratio_violation=False)
    db = Mock()

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("7.0"),
        current_position={"has_spot": True, "has_perp": True},
        hedge_status={"is_balanced": False, "hedge_ratio": Decimal("1.35")},
        db=db,
    )

    assert signal.signal_type == "REBALANCE"


def test_force_entry_bypasses_threshold(monkeypatch) -> None:
    events: list[str] = []

    def _capture(event, **_kwargs):
        events.append(event)

    monkeypatch.setattr("core.strategy.delta_neutral._log.warning", _capture)

    strategy = _strategy(force_entry=True)
    db = Mock()

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("-5.0"),
        current_position=None,
        hedge_status={"is_balanced": True},
        db=db,
    )

    assert signal.signal_type == "ENTER"
    assert "force_entry_override_active" in events


def test_paused_state_blocks_all_signals(monkeypatch) -> None:
    events: list[str] = []

    def _capture(event, **_kwargs):
        events.append(event)

    monkeypatch.setattr("core.strategy.delta_neutral._log.warning", _capture)

    strategy = _strategy()
    strategy.pause()

    # Not flat => remains paused.
    row = Mock()
    row.exchange = "coinbase_advanced"
    row.symbol = "ETH-PERP"
    row.position_type = "perp"
    row.quantity = Decimal("0.5")

    db = Mock()
    db.execute.return_value = _ScalarResult([row])

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("20.0"),
        current_position={"has_spot": True, "has_perp": True},
        hedge_status={"is_balanced": True},
        db=db,
    )

    assert signal.signal_type != "ENTER"
    assert "dn_strategy_paused" in events


def test_paused_state_clears_when_flat() -> None:
    strategy = _strategy()
    strategy.pause()

    db = Mock()
    db.execute.return_value = _ScalarResult([])

    signal = strategy.evaluate(
        account_name="paper_dn",
        eth_mark_price=Decimal("2367"),
        funding_rate_apr=Decimal("8.0"),
        current_position=None,
        hedge_status={"is_balanced": True},
        db=db,
    )

    assert strategy.is_paused is False
    assert signal.signal_type == "ENTER"
