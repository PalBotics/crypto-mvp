from datetime import datetime, timezone
from unittest.mock import Mock, patch

from apps.collector.collector import MarketDataCollector
from core.config.settings import Settings
from core.domain.contracts import FundingEvent, MarketEvent


def _ticker_payload() -> dict:
    return {
        "symbol": "BTC-USD",
        "bid": 50000.0,
        "ask": 50010.0,
        "last": 50005.0,
        "timestamp": datetime.now(timezone.utc),
    }


def test_collector_constructs_market_event(monkeypatch) -> None:
    adapter = Mock()
    adapter.name = "mock"
    adapter.fetch_ticker.return_value = _ticker_payload()

    monkeypatch.setattr("apps.collector.collector.get_exchange_adapter", lambda _: adapter)

    settings = Settings(
        _env_file=None,
        collect_exchange="mock",
        collect_symbol="BTC-USD",
        collect_interval_seconds=5,
        collect_funding=False,
        collect_funding_symbol="BTCUSDT",
    )
    collector = MarketDataCollector(settings=settings)
    session = Mock()

    with patch("apps.collector.collector.MarketEvent", wraps=MarketEvent) as market_event_cls:
        collector.collect_once(session)

    market_event_cls.assert_called_once()


def test_collector_constructs_funding_event_when_enabled(monkeypatch) -> None:
    adapter = Mock()
    adapter.name = "binance"
    adapter.fetch_ticker.return_value = _ticker_payload()
    adapter.fetch_funding_rate.return_value = {
        "symbol": "BTCUSDT",
        "exchange_symbol": "BTCUSDT",
        "funding_rate": 0.0001,
        "funding_interval_hours": 8,
        "predicted_funding_rate": None,
        "mark_price": 63123.45,
        "index_price": None,
        "next_funding_ts": None,
        "event_ts": datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
    }

    monkeypatch.setattr("apps.collector.collector.get_exchange_adapter", lambda _: adapter)

    monkeypatch.setenv("COLLECT_EXCHANGE", "binance")
    monkeypatch.setenv("COLLECT_FUNDING", "true")
    monkeypatch.setenv("COLLECT_FUNDING_SYMBOL", "BTCUSDT")

    settings = Settings(
        _env_file=None,
        collect_symbol="BTC-USD",
        collect_interval_seconds=5,
    )
    collector = MarketDataCollector(settings=settings)
    session = Mock()

    with patch("apps.collector.collector.FundingEvent", wraps=FundingEvent) as funding_event_cls:
        collector.collect_once(session)

    funding_event_cls.assert_called_once()
