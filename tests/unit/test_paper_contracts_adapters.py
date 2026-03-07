from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from core.domain.contracts import FillEvent
from core.models.market_tick import MarketTick
from core.models.order_intent import OrderIntent
from core.paper.contracts_adapters import (
    fill_event_to_record,
    market_tick_to_event,
    order_intent_to_contract,
    order_record_update_from_execution,
)
from core.paper.fees import FixedBpsFeeModel
from core.paper.simulator import PaperOrderSimulator


def test_order_intent_maps_to_contract() -> None:
    created_ts = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    strategy_signal_id = uuid4()
    portfolio_id = uuid4()

    intent = OrderIntent(
        strategy_signal_id=strategy_signal_id,
        portfolio_id=portfolio_id,
        mode="paper",
        exchange="coinbase",
        symbol="BTC-USD",
        side="buy",
        order_type="market",
        time_in_force=None,
        quantity=Decimal("1.5"),
        limit_price=None,
        reduce_only=False,
        post_only=False,
        client_order_id="cid-1",
        status="created",
        created_ts=created_ts,
    )

    contract = order_intent_to_contract(intent)

    assert contract.mode == "paper"
    assert contract.exchange == "coinbase"
    assert contract.symbol == "BTC-USD"
    assert contract.side == "buy"
    assert contract.order_type == "market"
    assert contract.quantity == Decimal("1.5")
    assert contract.status == "created"
    assert contract.created_ts == created_ts
    assert contract.strategy_signal_id == str(strategy_signal_id)
    assert contract.portfolio_id == str(portfolio_id)
    assert contract.client_order_id == "cid-1"


def test_market_tick_maps_to_market_event() -> None:
    event_ts = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    ingested_ts = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)

    tick = MarketTick(
        exchange="coinbase",
        adapter_name="coinbase",
        symbol="BTC-USD",
        exchange_symbol="BTC-USD",
        bid_price=Decimal("50000"),
        ask_price=Decimal("50010"),
        mid_price=Decimal("50005"),
        last_price=Decimal("50006"),
        bid_size=Decimal("1.0"),
        ask_size=Decimal("2.0"),
        event_ts=event_ts,
        ingested_ts=ingested_ts,
        sequence_id="seq-1",
    )

    event = market_tick_to_event(tick)

    assert event.exchange == "coinbase"
    assert event.adapter_name == "coinbase"
    assert event.symbol == "BTC-USD"
    assert event.exchange_symbol == "BTC-USD"
    assert event.bid_price == Decimal("50000")
    assert event.ask_price == Decimal("50010")
    assert event.mid_price == Decimal("50005")
    assert event.last_price == Decimal("50006")
    assert event.bid_size == Decimal("1.0")
    assert event.ask_size == Decimal("2.0")
    assert event.event_ts == event_ts
    assert event.ingested_ts == ingested_ts
    assert event.sequence_id == "seq-1"


def test_fill_event_maps_to_fill_record() -> None:
    fill_ts = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    ingested_ts = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    order_record_id = str(uuid4())

    fill = FillEvent(
        exchange="coinbase",
        symbol="BTC-USD",
        exchange_symbol="BTC-USD",
        side="buy",
        fill_price=Decimal("50010"),
        fill_qty=Decimal("2"),
        fill_notional=Decimal("100020"),
        fee_paid=Decimal("100.02"),
        fee_asset="USD",
        liquidity_role="taker",
        exchange_trade_id="trade-1",
        order_record_id=order_record_id,
        fill_ts=fill_ts,
        ingested_ts=ingested_ts,
    )

    record = fill_event_to_record(fill)

    assert str(record.order_record_id) == order_record_id
    assert record.exchange == "coinbase"
    assert record.symbol == "BTC-USD"
    assert record.side == "buy"
    assert record.fill_price == Decimal("50010")
    assert record.fill_qty == Decimal("2")
    assert record.fill_notional == Decimal("100020")
    assert record.fee_paid == Decimal("100.02")
    assert record.fee_asset == "USD"
    assert record.liquidity_role == "taker"
    assert record.exchange_trade_id == "trade-1"
    assert record.fill_ts == fill_ts
    assert record.ingested_ts == ingested_ts


def test_order_record_update_helper_for_filled_market_order() -> None:
    simulator = PaperOrderSimulator(fee_model=FixedBpsFeeModel(bps=Decimal("10")))

    intent = OrderIntent(
        strategy_signal_id=None,
        portfolio_id=None,
        mode="paper",
        exchange="coinbase",
        symbol="BTC-USD",
        side="buy",
        order_type="market",
        time_in_force=None,
        quantity=Decimal("2"),
        limit_price=None,
        reduce_only=False,
        post_only=False,
        client_order_id="cid-2",
        status="created",
        created_ts=datetime(2026, 3, 6, 11, 59, tzinfo=timezone.utc),
    )

    tick = MarketTick(
        exchange="coinbase",
        adapter_name="coinbase",
        symbol="BTC-USD",
        exchange_symbol="BTC-USD",
        bid_price=Decimal("50000"),
        ask_price=Decimal("50010"),
        mid_price=Decimal("50005"),
        last_price=Decimal("50006"),
        bid_size=None,
        ask_size=None,
        event_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
        ingested_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
        sequence_id=None,
    )

    execution = simulator.simulate(order_intent_to_contract(intent), market_tick_to_event(tick))
    update = order_record_update_from_execution(execution)

    assert update.status == "filled"
    assert update.submitted_qty == Decimal("2")
    assert update.filled_qty == Decimal("2")
    assert update.avg_fill_price == Decimal("50010")
    assert update.fees_paid == Decimal("100.02")
    assert update.created_ts == intent.created_ts
    assert update.updated_ts == tick.event_ts
    assert update.submitted_price is None
