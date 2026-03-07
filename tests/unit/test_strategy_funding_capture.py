from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from core.models.order_intent import OrderIntent
from core.models.position_snapshot import PositionSnapshot
from core.models.strategy_signal import StrategySignal
from core.strategy.funding_capture import FundingCaptureConfig, FundingCaptureStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config() -> FundingCaptureConfig:
    return FundingCaptureConfig(
        spot_symbol="BTC-USD",
        perp_symbol="BTC-PERP",
        exchange="binance",
        entry_funding_rate_threshold=Decimal("0.0001"),
        exit_funding_rate_threshold=Decimal("0.00005"),
        position_size=Decimal("1"),
        mode="paper",
    )


def _open_perp_position() -> PositionSnapshot:
    return PositionSnapshot(
        exchange="binance",
        account_name="paper",
        symbol="BTC-PERP",
        instrument_type="perpetual",
        side="sell",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=datetime(2026, 3, 7, 8, 0, tzinfo=timezone.utc),
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


# ---------------------------------------------------------------------------
# Entry tests
# ---------------------------------------------------------------------------

def test_entry_triggered_when_rate_above_threshold_and_no_position() -> None:
    """Rate >= entry threshold with no open position -> two OrderIntents + one StrategySignal."""
    session = Mock()
    session.execute.return_value = _ScalarResult(None)

    result = FundingCaptureStrategy(_config()).evaluate(
        session=session,
        funding_rate=Decimal("0.0002"),  # above 0.0001 threshold
        mark_price=Decimal("50000"),
    )

    assert result == "entered"

    added = [call.args[0] for call in session.add.call_args_list]
    assert len(added) == 3

    signal, spot_intent, perp_intent = added

    assert isinstance(signal, StrategySignal)
    assert signal.signal_type == "enter_funding_capture"
    assert signal.strategy_name == "funding_capture"
    assert signal.symbol == "BTC-PERP"

    assert isinstance(spot_intent, OrderIntent)
    assert spot_intent.symbol == "BTC-USD"
    assert spot_intent.side == "buy"
    assert spot_intent.order_type == "market"
    assert spot_intent.status == "pending"
    assert spot_intent.mode == "paper"
    assert spot_intent.reduce_only is False
    assert spot_intent.quantity == Decimal("1")

    assert isinstance(perp_intent, OrderIntent)
    assert perp_intent.symbol == "BTC-PERP"
    assert perp_intent.side == "sell"
    assert perp_intent.order_type == "market"
    assert perp_intent.status == "pending"
    assert perp_intent.mode == "paper"
    assert perp_intent.reduce_only is False
    assert perp_intent.quantity == Decimal("1")


def test_no_entry_when_rate_below_threshold() -> None:
    """Rate < entry threshold with no open position -> no_action, nothing written."""
    session = Mock()
    session.execute.return_value = _ScalarResult(None)

    result = FundingCaptureStrategy(_config()).evaluate(
        session=session,
        funding_rate=Decimal("0.00005"),  # below 0.0001 threshold
        mark_price=Decimal("50000"),
    )

    assert result == "no_action"
    session.add.assert_not_called()


def test_no_entry_when_position_already_open() -> None:
    """Rate >= entry threshold but position already open -> no_action, nothing written."""
    session = Mock()
    session.execute.return_value = _ScalarResult(_open_perp_position())

    result = FundingCaptureStrategy(_config()).evaluate(
        session=session,
        funding_rate=Decimal("0.0005"),  # well above threshold
        mark_price=Decimal("50000"),
    )

    assert result == "no_action"
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Exit tests
# ---------------------------------------------------------------------------

def test_exit_triggered_when_open_position_and_rate_at_or_below_exit_threshold() -> None:
    """Open position + rate <= exit threshold -> two closing OrderIntents + one StrategySignal."""
    session = Mock()
    session.execute.return_value = _ScalarResult(_open_perp_position())

    result = FundingCaptureStrategy(_config()).evaluate(
        session=session,
        funding_rate=Decimal("0.00003"),  # below 0.00005 exit threshold
        mark_price=Decimal("51000"),
    )

    assert result == "exited"

    added = [call.args[0] for call in session.add.call_args_list]
    assert len(added) == 3

    signal, spot_intent, perp_intent = added

    assert isinstance(signal, StrategySignal)
    assert signal.signal_type == "exit_funding_capture"

    assert isinstance(spot_intent, OrderIntent)
    assert spot_intent.symbol == "BTC-USD"
    assert spot_intent.side == "sell"
    assert spot_intent.reduce_only is True

    assert isinstance(perp_intent, OrderIntent)
    assert perp_intent.symbol == "BTC-PERP"
    assert perp_intent.side == "buy"
    assert perp_intent.reduce_only is True


def test_no_exit_when_no_open_position() -> None:
    """Rate below exit threshold but no open position -> no_action, nothing written."""
    session = Mock()
    session.execute.return_value = _ScalarResult(None)

    result = FundingCaptureStrategy(_config()).evaluate(
        session=session,
        funding_rate=Decimal("0.00001"),  # below exit threshold
        mark_price=Decimal("50000"),
    )

    assert result == "no_action"
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Field value correctness
# ---------------------------------------------------------------------------

def test_correct_sides_and_symbols_on_entry_intents() -> None:
    """Verify exact field values on both entry OrderIntents."""
    session = Mock()
    session.execute.return_value = _ScalarResult(None)

    FundingCaptureStrategy(_config()).evaluate(
        session=session,
        funding_rate=Decimal("0.0003"),
        mark_price=Decimal("49000"),
    )

    added = [call.args[0] for call in session.add.call_args_list]
    _, spot_intent, perp_intent = added

    # Spot leg: buy the underlying
    assert spot_intent.symbol == "BTC-USD"
    assert spot_intent.side == "buy"
    assert spot_intent.exchange == "binance"
    assert spot_intent.mode == "paper"
    assert spot_intent.order_type == "market"
    assert spot_intent.reduce_only is False
    assert spot_intent.post_only is False
    assert spot_intent.limit_price is None
    assert isinstance(spot_intent.quantity, Decimal)

    # Perp leg: short the perpetual
    assert perp_intent.symbol == "BTC-PERP"
    assert perp_intent.side == "sell"
    assert perp_intent.exchange == "binance"
    assert perp_intent.mode == "paper"
    assert perp_intent.order_type == "market"
    assert perp_intent.reduce_only is False
    assert perp_intent.post_only is False
    assert perp_intent.limit_price is None
    assert isinstance(perp_intent.quantity, Decimal)
