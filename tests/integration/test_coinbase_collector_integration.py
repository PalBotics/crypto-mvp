"""Integration test for Coinbase adapter with collector flow.

Tests that the Coinbase adapter output is compatible with collector data flow.
Uses mocked HTTP responses to avoid external API calls.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from core.config.settings import Settings
from core.exchange.coinbase_adapter import CoinbaseAdapter
from core.exchange.factory import get_exchange_adapter


@pytest.fixture
def coinbase_settings():
    """Create settings configured for Coinbase."""
    return Settings(
        collect_exchange="coinbase",
        collect_symbol="BTC-USD",
        collect_interval_seconds=5,
    )


def test_coinbase_adapter_returns_expected_ticker_format():
    """Test that Coinbase adapter returns ticker in the format collector expects."""
    
    # Mock Coinbase API response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "trades": [],
        "best_bid": "50000.00",
        "best_ask": "50001.50",
        "price": "50000.75",
    }

    adapter = CoinbaseAdapter()
    
    with patch.object(adapter.session, "request", return_value=mock_response):
        ticker = adapter.fetch_ticker("BTC-USD")
        
        # Verify all required fields are present
        assert "symbol" in ticker
        assert "bid" in ticker
        assert "ask" in ticker
        assert "last" in ticker
        assert "timestamp" in ticker
        
        # Verify field types
        assert isinstance(ticker["symbol"], str)
        assert isinstance(ticker["bid"], float)
        assert isinstance(ticker["ask"], float)
        assert isinstance(ticker["last"], float)
        assert isinstance(ticker["timestamp"], datetime)
        
        # Verify values
        assert ticker["symbol"] == "BTC-USD"
        assert ticker["bid"] == 50000.00
        assert ticker["ask"] == 50001.50
        assert ticker["last"] == 50000.75
        
        # Verify timestamp is timezone-aware UTC
        assert ticker["timestamp"].tzinfo is not None
        assert ticker["timestamp"].tzinfo == timezone.utc


def test_collector_can_process_coinbase_ticker_data():
    """Test that collector logic can handle Coinbase ticker data."""
    # This simulates what collector.collect_once() does with ticker data
    
    # Sample Coinbase ticker response
    ticker = {
        "symbol": "BTC-USD",
        "bid": 50000.00,
        "ask": 50001.50,
        "last": 50000.75,
        "timestamp": datetime.now(timezone.utc),
    }
    
    # Simulate MarketTick creation logic from collector
    bid_price = Decimal(str(ticker["bid"]))
    ask_price = Decimal(str(ticker["ask"]))
    mid_price = Decimal(str((ticker["bid"] + ticker["ask"]) / 2))
    last_price = Decimal(str(ticker["last"]))
    event_ts = ticker["timestamp"]
    
    # Verify all conversions work
    assert isinstance(bid_price, Decimal)
    assert isinstance(ask_price, Decimal)
    assert isinstance(mid_price, Decimal)
    assert isinstance(last_price, Decimal)
    assert isinstance(event_ts, datetime)
    
    # Verify values
    assert bid_price == Decimal("50000.00")
    assert ask_price == Decimal("50001.50")
    assert last_price == Decimal("50000.75")
    assert mid_price == Decimal("50000.75")  # (50000.00 + 50001.50) / 2
    
    # Verify timestamp is timezone-aware
    assert event_ts.tzinfo is not None


def test_factory_integration_with_coinbase():
    """Test that factory returns correct adapter for 'coinbase'."""
    adapter = get_exchange_adapter("coinbase")
    
    assert isinstance(adapter, CoinbaseAdapter)
    assert adapter.name == "coinbase"


def test_factory_integration_case_insensitive():
    """Test that factory handles case-insensitive exchange names."""
    for name in ["coinbase", "Coinbase", "COINBASE", "CoInBaSe"]:
        adapter = get_exchange_adapter(name)
        assert isinstance(adapter, CoinbaseAdapter)
        assert adapter.name == "coinbase"
