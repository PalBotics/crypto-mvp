from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from apps.collector.collector import MarketDataCollector
from core.config.settings import Settings
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick


def _ticker_payload() -> dict:
    return {
        "symbol": "BTC-USD",
        "bid": 50000.0,
        "ask": 50010.0,
        "last": 50005.0,
        "timestamp": datetime.now(timezone.utc),
    }


def test_funding_disabled_persists_market_tick_only(monkeypatch) -> None:
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

    collector.collect_once(session)

    adapter.fetch_ticker.assert_called_once_with("BTC-USD")
    adapter.fetch_funding_rate.assert_not_called()

    added = [call.args[0] for call in session.add.call_args_list]
    assert len(added) == 1
    assert isinstance(added[0], MarketTick)
    session.commit.assert_called_once()


def test_funding_enabled_persists_snapshot_when_payload_returned(monkeypatch) -> None:
    adapter = Mock()
    adapter.name = "binance"
    adapter.fetch_ticker.return_value = _ticker_payload()
    funding_event_ts = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    adapter.fetch_funding_rate.return_value = {
        "symbol": "BTCUSDT",
        "exchange_symbol": "BTCUSDT",
        "funding_rate": 0.0001,
        "funding_interval_hours": 8,
        "predicted_funding_rate": None,
        "mark_price": 63123.45,
        "index_price": None,
        "next_funding_ts": None,
        "event_ts": funding_event_ts,
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

    collector.collect_once(session)

    adapter.fetch_ticker.assert_called_once_with("BTC-USD")
    adapter.fetch_funding_rate.assert_called_once_with("BTCUSDT")

    added = [call.args[0] for call in session.add.call_args_list]
    assert len(added) == 2
    assert isinstance(added[0], MarketTick)
    assert isinstance(added[1], FundingRateSnapshot)

    snapshot = added[1]
    assert snapshot.exchange == "binance"
    assert snapshot.adapter_name == "binance"
    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.exchange_symbol == "BTCUSDT"
    assert snapshot.funding_rate == Decimal("0.0001")
    assert snapshot.funding_interval_hours == 8
    assert snapshot.predicted_funding_rate is None
    assert snapshot.mark_price == Decimal("63123.45")
    assert snapshot.index_price is None
    assert snapshot.next_funding_ts is None
    assert snapshot.event_ts == funding_event_ts

    session.commit.assert_called_once()


def test_funding_enabled_none_payload_skips_snapshot_and_succeeds(monkeypatch) -> None:
    adapter = Mock()
    adapter.name = "coinbase"
    adapter.fetch_ticker.return_value = _ticker_payload()
    adapter.fetch_funding_rate.return_value = None

    monkeypatch.setattr("apps.collector.collector.get_exchange_adapter", lambda _: adapter)
    monkeypatch.setenv("COLLECT_EXCHANGE", "coinbase")
    monkeypatch.setenv("COLLECT_FUNDING", "true")
    monkeypatch.setenv("COLLECT_FUNDING_SYMBOL", "BTCUSDT")

    settings = Settings(
        _env_file=None,
        collect_symbol="BTC-USD",
        collect_interval_seconds=5,
    )
    collector = MarketDataCollector(settings=settings)

    session = Mock()

    collector.collect_once(session)

    adapter.fetch_ticker.assert_called_once_with("BTC-USD")
    adapter.fetch_funding_rate.assert_called_once_with("BTCUSDT")

    added = [call.args[0] for call in session.add.call_args_list]
    assert len(added) == 1
    assert isinstance(added[0], MarketTick)
    session.commit.assert_called_once()
