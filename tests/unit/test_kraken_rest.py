from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from apps.collector.kraken_rest import CollectorConfig, CollectorError, KrakenRestAdapter


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _spot_fixture() -> dict:
    return {
        "error": [],
        "result": {
            "XXBTZUSD": {
                "b": ["29100.1", "1", "1"],
                "a": ["29105.2", "1", "1"],
                "c": ["29102.3", "0.1"],
            }
        },
    }


def _futures_ticker_fixture() -> dict:
    return {
        "symbol": "PF_XBTUSD",
        "bid": 29100.0,
        "ask": 29105.0,
        "last": 29102.0,
        "markPrice": 29103.0,
        "indexPrice": 29101.0,
        "fundingRate": 0.0001,
        "fundingRateRelative": 0.0001,
        "next_funding_rate_time": "2024-01-01T04:00:00Z",
    }


def _adapter() -> KrakenRestAdapter:
    return KrakenRestAdapter(CollectorConfig())


def _order_book_fixture() -> dict:
    return {
        "error": [],
        "result": {
            "XXBTZUSD": {
                "bids": [
                    ["29100.10", "1.25000000", 1704067200],
                    ["29100.00", "0.50000000", 1704067200],
                    ["29099.90", "0.75000000", 1704067200],
                ],
                "asks": [
                    ["29100.30", "1.10000000", 1704067200],
                    ["29100.40", "0.40000000", 1704067200],
                    ["29100.50", "0.90000000", 1704067200],
                ],
            }
        },
    }


def test_parse_spot_tick_maps_fields_correctly() -> None:
    adapter = _adapter()
    tick = adapter.parse_spot_tick(_spot_fixture())

    assert tick.exchange == "kraken"
    assert tick.symbol == "XBTUSD"
    assert tick.exchange_symbol == "XXBTZUSD"
    assert isinstance(tick.bid_price, Decimal)
    assert isinstance(tick.ask_price, Decimal)
    assert isinstance(tick.last_price, Decimal)
    assert tick.bid_price == Decimal("29100.1")
    assert tick.ask_price == Decimal("29105.2")
    assert tick.last_price == Decimal("29102.3")
    assert tick.mid_price == (tick.bid_price + tick.ask_price) / Decimal("2")
    assert tick.event_ts.tzinfo is not None


def test_parse_perp_tick_maps_fields_correctly() -> None:
    adapter = _adapter()
    tick = adapter.parse_perp_tick(_futures_ticker_fixture())

    assert tick.exchange == "kraken_futures"
    assert tick.symbol == "XBTUSD"
    assert tick.exchange_symbol == "PF_XBTUSD"
    assert isinstance(tick.bid_price, Decimal)
    assert isinstance(tick.ask_price, Decimal)
    assert isinstance(tick.last_price, Decimal)
    assert tick.bid_price == Decimal("29100.0")
    assert tick.ask_price == Decimal("29105.0")
    assert tick.last_price == Decimal("29102.0")
    assert tick.mid_price == (tick.bid_price + tick.ask_price) / Decimal("2")
    assert tick.event_ts.tzinfo is not None


def test_parse_funding_snapshot_maps_fields_correctly() -> None:
    adapter = _adapter()
    snapshot = adapter.parse_funding_snapshot(_futures_ticker_fixture())

    assert snapshot.exchange == "kraken_futures"
    assert snapshot.symbol == "XBTUSD"
    assert snapshot.exchange_symbol == "PF_XBTUSD"
    assert isinstance(snapshot.funding_rate, Decimal)
    assert isinstance(snapshot.mark_price, Decimal)
    assert isinstance(snapshot.index_price, Decimal)
    assert snapshot.funding_rate == Decimal("0.0001")
    assert snapshot.mark_price == Decimal("29103.0")
    assert snapshot.index_price == Decimal("29101.0")
    assert snapshot.funding_interval_hours == 4
    assert snapshot.next_funding_ts is not None
    assert snapshot.next_funding_ts.tzinfo is not None
    assert isinstance(snapshot.predicted_funding_rate, Decimal)


def test_decimal_fields_not_float_on_returned_objects() -> None:
    adapter = _adapter()
    spot_tick = adapter.parse_spot_tick(_spot_fixture())
    perp_tick = adapter.parse_perp_tick(_futures_ticker_fixture())
    funding = adapter.parse_funding_snapshot(_futures_ticker_fixture())

    assert isinstance(spot_tick.bid_price, Decimal)
    assert not isinstance(spot_tick.bid_price, float)
    assert isinstance(perp_tick.ask_price, Decimal)
    assert not isinstance(perp_tick.ask_price, float)
    assert isinstance(funding.funding_rate, Decimal)
    assert not isinstance(funding.funding_rate, float)


def test_fetch_spot_ticker_raises_on_http_non_200(monkeypatch) -> None:
    def _fake_get(*_args, **_kwargs):
        return _FakeResponse(status_code=500, payload={})

    monkeypatch.setattr("apps.collector.kraken_rest.httpx.get", _fake_get)

    adapter = _adapter()
    with pytest.raises(CollectorError):
        adapter.fetch_spot_ticker()


def test_fetch_spot_ticker_raises_on_spot_error_field(monkeypatch) -> None:
    payload = {"error": ["EQuery:Unknown"], "result": {}}

    def _fake_get(*_args, **_kwargs):
        return _FakeResponse(status_code=200, payload=payload)

    monkeypatch.setattr("apps.collector.kraken_rest.httpx.get", _fake_get)

    adapter = _adapter()
    with pytest.raises(CollectorError):
        adapter.fetch_spot_ticker()


def test_parse_funding_snapshot_missing_funding_rate_returns_zero() -> None:
    adapter = _adapter()
    raw = _futures_ticker_fixture()
    raw.pop("fundingRate")

    snapshot = adapter.parse_funding_snapshot(raw)

    assert snapshot.funding_rate == Decimal("0")


def test_fetch_futures_tickers_returns_list(monkeypatch) -> None:
    payload = {"tickers": [_futures_ticker_fixture()]}

    def _fake_get(*_args, **_kwargs):
        return _FakeResponse(status_code=200, payload=payload)

    monkeypatch.setattr("apps.collector.kraken_rest.httpx.get", _fake_get)

    adapter = _adapter()
    tickers = adapter.fetch_futures_tickers()

    assert isinstance(tickers, list)
    assert tickers[0]["symbol"] == "PF_XBTUSD"


def test_fetch_order_book_raises_on_non_200(monkeypatch) -> None:
    def _fake_get(*_args, **_kwargs):
        return _FakeResponse(status_code=500, payload={})

    monkeypatch.setattr("apps.collector.kraken_rest.httpx.get", _fake_get)

    adapter = _adapter()
    with pytest.raises(CollectorError):
        adapter.fetch_order_book()


def test_parse_order_book_snapshot_maps_fields_correctly() -> None:
    adapter = _adapter()

    snapshot = adapter.parse_order_book_snapshot(_order_book_fixture())

    assert snapshot.exchange == "kraken"
    assert snapshot.symbol == "XBTUSD"
    assert isinstance(snapshot.bid_price_1, Decimal)
    assert isinstance(snapshot.ask_price_1, Decimal)
    assert snapshot.spread == snapshot.ask_price_1 - snapshot.bid_price_1
    assert snapshot.mid_price == (snapshot.bid_price_1 + snapshot.ask_price_1) / Decimal("2")
    assert isinstance(snapshot.spread_bps, Decimal)
    assert snapshot.event_ts.tzinfo is not None
    assert snapshot.event_ts.tzinfo == timezone.utc


def test_parse_order_book_snapshot_level_2_and_3_populated() -> None:
    adapter = _adapter()

    snapshot = adapter.parse_order_book_snapshot(_order_book_fixture())

    assert isinstance(snapshot.bid_price_2, Decimal)
    assert isinstance(snapshot.ask_price_2, Decimal)
    assert isinstance(snapshot.bid_price_3, Decimal)
    assert isinstance(snapshot.ask_price_3, Decimal)


def test_parse_order_book_snapshot_all_prices_are_decimal() -> None:
    adapter = _adapter()

    snapshot = adapter.parse_order_book_snapshot(_order_book_fixture())

    fields = [
        snapshot.bid_price_1,
        snapshot.bid_size_1,
        snapshot.ask_price_1,
        snapshot.ask_size_1,
        snapshot.bid_price_2,
        snapshot.bid_size_2,
        snapshot.ask_price_2,
        snapshot.ask_size_2,
        snapshot.bid_price_3,
        snapshot.bid_size_3,
        snapshot.ask_price_3,
        snapshot.ask_size_3,
        snapshot.spread,
        snapshot.spread_bps,
        snapshot.mid_price,
    ]

    for value in fields:
        if value is not None:
            assert isinstance(value, Decimal)
            assert not isinstance(value, float)
