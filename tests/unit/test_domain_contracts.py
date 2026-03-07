from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.domain import (
    FillEvent,
    FundingEvent,
    MarketEvent,
    OrderIntentContract,
    ensure_utc,
    normalize_symbol,
    to_decimal,
)


def test_to_decimal_converts_numeric_inputs() -> None:
    assert to_decimal("1.23") == Decimal("1.23")
    assert to_decimal(10) == Decimal("10")
    assert to_decimal(0.5) == Decimal("0.5")


def test_ensure_utc_converts_aware_datetime() -> None:
    source = datetime(2026, 3, 6, 10, 0, tzinfo=timezone(timedelta(hours=-5)))

    result = ensure_utc(source)

    assert result.tzinfo == timezone.utc
    assert result.hour == 15


def test_ensure_utc_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ensure_utc(datetime(2026, 3, 6, 10, 0))


def test_normalize_symbol_for_known_exchanges() -> None:
    symbol, exchange_symbol = normalize_symbol("binance", "btc-usdt")
    assert symbol == "BTC-USDT"
    assert exchange_symbol == "BTCUSDT"

    symbol, exchange_symbol = normalize_symbol("coinbase", "btc/usd")
    assert symbol == "BTC/USD"
    assert exchange_symbol == "BTC-USD"


def test_normalize_symbol_for_unknown_exchange_is_minimal() -> None:
    symbol, exchange_symbol = normalize_symbol("kraken", "eth/usd")
    assert symbol == "ETH/USD"
    assert exchange_symbol == "ETH/USD"


def test_market_event_construction() -> None:
    event = MarketEvent(
        exchange="coinbase",
        adapter_name="coinbase",
        symbol="btc/usd",
        bid_price="50000.00",
        ask_price=50001.0,
        mid_price="50000.50",
        last_price=50000.75,
        bid_size="1.25",
        ask_size="0.75",
        event_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
        ingested_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
    )

    assert event.symbol == "BTC/USD"
    assert event.exchange_symbol == "BTC-USD"
    assert event.bid_price == Decimal("50000.00")
    assert event.ask_price == Decimal("50001.0")
    assert event.mid_price == Decimal("50000.50")
    assert event.last_price == Decimal("50000.75")
    assert event.bid_size == Decimal("1.25")
    assert event.ask_size == Decimal("0.75")


def test_funding_event_construction() -> None:
    event = FundingEvent(
        exchange="binance",
        adapter_name="binance",
        symbol="btc-usdt",
        funding_rate="0.0001",
        funding_interval_hours=8,
        mark_price="63123.45",
        event_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
        ingested_ts=datetime(2026, 3, 6, 12, 1, tzinfo=timezone.utc),
        next_funding_ts=datetime(2026, 3, 6, 16, 0, tzinfo=timezone.utc),
    )

    assert event.symbol == "BTC-USDT"
    assert event.exchange_symbol == "BTCUSDT"
    assert event.funding_rate == Decimal("0.0001")
    assert event.mark_price == Decimal("63123.45")
    assert event.funding_interval_hours == 8
    assert event.next_funding_ts is not None
    assert event.next_funding_ts.tzinfo == timezone.utc


def test_order_intent_contract_construction() -> None:
    contract = OrderIntentContract(
        mode="paper",
        exchange="binance",
        symbol="eth/usdt",
        side="buy",
        order_type="limit",
        quantity="1.5",
        limit_price="2500.25",
        status="created",
        created_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
    )

    assert contract.symbol == "ETH/USDT"
    assert contract.exchange_symbol == "ETHUSDT"
    assert contract.quantity == Decimal("1.5")
    assert contract.limit_price == Decimal("2500.25")
    assert contract.created_ts.tzinfo == timezone.utc


def test_fill_event_construction() -> None:
    event = FillEvent(
        exchange="coinbase",
        symbol="eth/usd",
        side="buy",
        fill_price="2500.00",
        fill_qty="0.1",
        fill_notional="250.0",
        fee_paid="0.25",
        fee_asset="USD",
        fill_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
        ingested_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
    )

    assert event.symbol == "ETH/USD"
    assert event.exchange_symbol == "ETH-USD"
    assert event.fill_price == Decimal("2500.00")
    assert event.fill_qty == Decimal("0.1")
    assert event.fill_notional == Decimal("250.0")
    assert event.fee_paid == Decimal("0.25")
