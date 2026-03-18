from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from apps.collector.collector_loop import CollectorLoop
from apps.collector.kraken_rest import CollectorConfig, KrakenRestAdapter
from core.config.settings import Settings
from core.exchange.coinbase_advanced import CoinbaseAdvancedAdapter
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick
from core.models.order_book_snapshot import OrderBookSnapshot


def _coinbase_product_fixture() -> dict:
    return {
        "product_id": "ETH-PERP-INTX",
        "price": "3521.23",
        "best_bid": "3521.10",
        "best_ask": "3521.40",
        "future_product_details": {
            "funding_interval": "ONE_HOUR",
            "funding_rate": "0.000025",
            "next_funding_rate": "0.000030",
            "perpetual_details": {
                "funding_rate": "0.000025",
                "next_funding_rate": "0.000030",
                "mark_price": "3521.27",
                "funding_time": "2026-03-16T12:00:00Z",
            },
        },
    }


def _kraken_spot_fixture() -> dict:
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


def _kraken_futures_fixture() -> list[dict]:
    return [
        {
            "symbol": "PF_XBTUSD",
            "bid": 29100.0,
            "ask": 29105.0,
            "last": 29102.0,
            "markPrice": 29103.0,
            "indexPrice": 29101.0,
            "fundingRate": 0.0001,
            "fundingRateRelative": 0.0001,
            "next_funding_rate_time": "2026-03-16T12:00:00Z",
        }
    ]


def _kraken_order_book_fixture() -> dict:
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


def test_get_ticker_returns_normalized_market_tick(monkeypatch) -> None:
    adapter = CoinbaseAdvancedAdapter(api_key="k", private_key="p")
    monkeypatch.setattr(adapter, "_get_product_with_retry", lambda: _coinbase_product_fixture())

    tick = adapter.get_ticker("ETH-PERP")

    assert tick is not None
    assert tick.exchange == "coinbase_advanced"
    assert tick.symbol == "ETH-PERP"
    assert isinstance(tick, MarketTick)
    assert isinstance(tick.bid_price, Decimal)
    assert isinstance(tick.ask_price, Decimal)
    assert isinstance(tick.mid_price, Decimal)
    assert isinstance(tick.last_price, Decimal)
    assert not isinstance(tick.bid_price, float)
    assert tick.bid_price < tick.mid_price < tick.ask_price


def test_get_funding_rate_returns_normalized_snapshot(monkeypatch) -> None:
    adapter = CoinbaseAdvancedAdapter(api_key="k", private_key="p")
    monkeypatch.setattr(adapter, "_get_product_with_retry", lambda: _coinbase_product_fixture())

    snapshot = adapter.get_funding_rate("ETH-PERP")

    assert snapshot is not None
    assert isinstance(snapshot, FundingRateSnapshot)
    assert snapshot.exchange == "coinbase_advanced"
    assert snapshot.symbol == "ETH-PERP"
    assert isinstance(snapshot.funding_rate, Decimal)
    assert snapshot.funding_rate == Decimal("0.000025")
    assert snapshot.funding_interval_hours == 1


def test_adapter_returns_none_on_http_error(monkeypatch) -> None:
    adapter = CoinbaseAdvancedAdapter(api_key="k", private_key="p")
    events: list[tuple[str, dict]] = []

    def _capture_error(event: str, **kwargs) -> None:
        events.append((event, kwargs))

    monkeypatch.setattr("core.exchange.coinbase_advanced._log.error", _capture_error)
    monkeypatch.setattr(adapter, "_get_product", lambda: (_ for _ in ()).throw(RuntimeError("Coinbase HTTP status 401")))

    tick = adapter.get_ticker("ETH-PERP")

    assert tick is None
    assert any(name == "coinbase_request_failed" for name, _ in events)


def test_adapter_disabled_when_credentials_empty(monkeypatch, db_session) -> None:
    info_events: list[tuple[str, dict]] = []

    def _capture_info(event: str, **kwargs) -> None:
        info_events.append((event, kwargs))

    monkeypatch.setattr("core.exchange.coinbase_advanced._log.info", _capture_info)

    coinbase_adapter = CoinbaseAdvancedAdapter(api_key="", private_key="")
    assert coinbase_adapter.is_enabled is False
    assert any(name == "coinbase_adapter_disabled" for name, _ in info_events)

    config = CollectorConfig()
    kraken_adapter = KrakenRestAdapter(config)

    monkeypatch.setattr(kraken_adapter, "fetch_spot_ticker", lambda: _kraken_spot_fixture())
    monkeypatch.setattr(kraken_adapter, "fetch_futures_tickers", lambda: _kraken_futures_fixture())
    monkeypatch.setattr(kraken_adapter, "fetch_order_book", lambda: _kraken_order_book_fixture())

    loop = CollectorLoop(
        config=config,
        adapter=kraken_adapter,
        coinbase_adapter=coinbase_adapter,
        session_factory=lambda: db_session,
    )

    loop._poll_once(db_session)

    assert db_session.query(MarketTick).count() >= 2
    assert db_session.query(FundingRateSnapshot).count() >= 1
    assert db_session.query(OrderBookSnapshot).count() >= 1


def test_private_key_newline_handling() -> None:
    settings = Settings(
        _env_file=None,
        COINBASE_PRIVATE_KEY="-----BEGIN EC PRIVATE KEY-----\\nKEY_LINE\\n-----END EC PRIVATE KEY-----",
    )

    pem = settings.coinbase_private_key_pem

    assert "\\n" not in pem
    assert "\n" in pem
    assert pem.startswith("-----BEGIN EC PRIVATE KEY-----\n")
    assert pem.endswith("\n-----END EC PRIVATE KEY-----")
