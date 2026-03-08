from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

from core.models.order_book_snapshot import OrderBookSnapshot
from core.strategy.market_making import MarketMakingConfig, MarketMakingStrategy


def _config() -> MarketMakingConfig:
    return MarketMakingConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        spread_bps=Decimal("20"),
        quote_size=Decimal("0.001"),
        max_inventory=Decimal("0.01"),
        min_spread_bps=Decimal("5"),
        stale_book_seconds=120,
    )


def _order_book(*, spread_bps: Decimal = Decimal("8"), event_ts: datetime | None = None) -> OrderBookSnapshot:
    ts = event_ts or datetime.now(timezone.utc)
    mid = Decimal("60000")
    spread = mid * spread_bps / Decimal("10000")
    return OrderBookSnapshot(
        exchange="kraken",
        adapter_name="kraken_rest",
        symbol="XBTUSD",
        exchange_symbol="XXBTZUSD",
        bid_price_1=mid - spread / Decimal("2"),
        bid_size_1=Decimal("1"),
        ask_price_1=mid + spread / Decimal("2"),
        ask_size_1=Decimal("1"),
        bid_price_2=mid - Decimal("1"),
        bid_size_2=Decimal("1"),
        ask_price_2=mid + Decimal("1"),
        ask_size_2=Decimal("1"),
        bid_price_3=mid - Decimal("2"),
        bid_size_3=Decimal("1"),
        ask_price_3=mid + Decimal("2"),
        ask_size_3=Decimal("1"),
        spread=spread,
        spread_bps=spread_bps,
        mid_price=mid,
        event_ts=ts,
        ingested_ts=ts,
    )


def test_generates_bid_and_ask_when_conditions_met() -> None:
    strategy = MarketMakingStrategy(_config())

    intents = strategy.evaluate(
        session=Mock(),
        order_book=_order_book(),
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    assert len(intents) == 2
    bid = next(i for i in intents if i.side == "buy")
    ask = next(i for i in intents if i.side == "sell")
    assert bid.limit_price < Decimal(str(_order_book().mid_price)) < ask.limit_price
    assert isinstance(bid.limit_price, Decimal)
    assert isinstance(ask.limit_price, Decimal)


def test_suppresses_bid_at_max_long_inventory() -> None:
    config = _config()
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=Mock(),
        order_book=_order_book(),
        current_position=config.max_inventory,
        current_ts=datetime.now(timezone.utc),
    )

    assert len(intents) == 1
    assert intents[0].side == "sell"


def test_suppresses_ask_at_max_short_inventory() -> None:
    config = _config()
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=Mock(),
        order_book=_order_book(),
        current_position=-config.max_inventory,
        current_ts=datetime.now(timezone.utc),
    )

    assert len(intents) == 1
    assert intents[0].side == "buy"


def test_returns_empty_on_stale_book() -> None:
    strategy = MarketMakingStrategy(_config())
    stale_ts = datetime.now(timezone.utc) - timedelta(seconds=180)

    intents = strategy.evaluate(
        session=Mock(),
        order_book=_order_book(event_ts=stale_ts),
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    assert intents == []


def test_returns_empty_when_spread_too_tight() -> None:
    strategy = MarketMakingStrategy(_config())

    intents = strategy.evaluate(
        session=Mock(),
        order_book=_order_book(spread_bps=Decimal("1")),
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    assert intents == []


def test_bid_price_below_mid_ask_price_above_mid() -> None:
    strategy = MarketMakingStrategy(_config())
    book = _order_book()

    intents = strategy.evaluate(
        session=Mock(),
        order_book=book,
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    bid = next(i for i in intents if i.side == "buy")
    ask = next(i for i in intents if i.side == "sell")
    assert bid.limit_price < book.mid_price
    assert ask.limit_price > book.mid_price


def test_prices_rounded_to_one_decimal_place() -> None:
    strategy = MarketMakingStrategy(_config())
    book = _order_book()

    intents = strategy.evaluate(
        session=Mock(),
        order_book=book,
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    for intent in intents:
        text = format(intent.limit_price, "f")
        decimals = text.split(".")[1] if "." in text else ""
        assert len(decimals.rstrip("0")) <= 1


def test_intent_fields_are_correct() -> None:
    config = _config()
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=Mock(),
        order_book=_order_book(),
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    for intent in intents:
        assert intent.intent_type == "limit"
        assert intent.quantity == config.quote_size
        assert intent.mode == "paper"
        assert intent.strategy_name == "market_making"
        assert intent.status == "pending"
        assert intent.reduce_only is False
