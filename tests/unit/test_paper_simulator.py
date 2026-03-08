from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.domain.contracts import MarketEvent, OrderIntentContract
from core.paper.fees import FixedBpsFeeModel
from core.paper.simulator import PaperOrderSimulator


def _market_event() -> MarketEvent:
    ts = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    return MarketEvent(
        exchange="coinbase",
        adapter_name="coinbase",
        symbol="BTC-USD",
        exchange_symbol="BTC-USD",
        bid_price=Decimal("50000"),
        ask_price=Decimal("50010"),
        mid_price=Decimal("50005"),
        last_price=Decimal("50006"),
        event_ts=ts,
        ingested_ts=ts,
    )


def _order_intent(*, side: str, mode: str = "paper", order_type: str = "market") -> OrderIntentContract:
    return OrderIntentContract(
        mode=mode,
        exchange="coinbase",
        symbol="BTC-USD",
        exchange_symbol="BTC-USD",
        side=side,
        order_type=order_type,
        quantity=Decimal("2"),
        status="created",
        created_ts=datetime(2026, 3, 6, 11, 59, tzinfo=timezone.utc),
    )


def test_buy_market_order_fills_at_ask() -> None:
    simulator = PaperOrderSimulator(fee_model=FixedBpsFeeModel(bps=Decimal("10")))

    result = simulator.simulate(_order_intent(side="buy"), _market_event())

    assert result.average_fill_price == Decimal("50010")
    assert result.fill_event.fill_price == Decimal("50010")
    assert result.order_status == "filled"


def test_sell_market_order_fills_at_bid() -> None:
    simulator = PaperOrderSimulator(fee_model=FixedBpsFeeModel(bps=Decimal("10")))

    result = simulator.simulate(_order_intent(side="sell"), _market_event())

    assert result.average_fill_price == Decimal("50000")
    assert result.fill_event.fill_price == Decimal("50000")
    assert result.order_status == "filled"


def test_fill_notional_and_fee_are_correct() -> None:
    simulator = PaperOrderSimulator(fee_model=FixedBpsFeeModel(bps=Decimal("10")))

    result = simulator.simulate(_order_intent(side="buy"), _market_event())

    expected_notional = Decimal("50010") * Decimal("2")
    expected_fee = expected_notional * Decimal("10") / Decimal("10000")

    assert result.fill_event.fill_notional == expected_notional
    assert result.fee_paid == expected_fee
    assert result.fill_event.fee_paid == expected_fee


def test_replay_mode_is_accepted() -> None:
    simulator = PaperOrderSimulator(fee_model=FixedBpsFeeModel(bps=Decimal("10")))

    result = simulator.simulate(_order_intent(side="buy", mode="replay"), _market_event())

    assert result.order_status == "filled"


def test_paper_mode_is_accepted() -> None:
    simulator = PaperOrderSimulator(fee_model=FixedBpsFeeModel(bps=Decimal("10")))

    result = simulator.simulate(_order_intent(side="buy", mode="paper"), _market_event())

    assert result.order_status == "filled"


def test_unsupported_order_type_raises_clear_error() -> None:
    simulator = PaperOrderSimulator(fee_model=FixedBpsFeeModel(bps=Decimal("10")))

    with pytest.raises(ValueError, match="Unsupported order_type"):
        simulator.simulate(_order_intent(side="buy", order_type="limit"), _market_event())


def test_unsupported_mode_raises_clear_error() -> None:
    simulator = PaperOrderSimulator(fee_model=FixedBpsFeeModel(bps=Decimal("10")))

    with pytest.raises(ValueError, match="Unsupported mode"):
        simulator.simulate(_order_intent(side="buy", mode="live"), _market_event())
