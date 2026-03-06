"""Unit tests for CoinbaseAdapter.

Tests use mocked HTTP responses to avoid external API calls.
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from core.exchange.coinbase_adapter import CoinbaseAdapter
from core.exchange.exceptions import (
    ExchangeConnectionError,
    ExchangeError,
    ExchangeRateLimitError,
)


@pytest.fixture
def adapter():
    """Create a CoinbaseAdapter instance for testing."""
    return CoinbaseAdapter()


class TestCoinbaseAdapterBasics:
    """Test basic adapter properties and initialization."""

    def test_adapter_name(self, adapter):
        """Adapter name should be 'coinbase'."""
        assert adapter.name == "coinbase"

    def test_base_url(self, adapter):
        """Base URL should point to Coinbase Advanced Trade API."""
        assert adapter.BASE_URL == "https://api.coinbase.com/api/v3/brokerage"

    def test_session_headers(self, adapter):
        """Session should have required headers."""
        assert adapter.session.headers["Accept"] == "application/json"
        assert "crypto-mvp" in adapter.session.headers["User-Agent"]


class TestGetServerTime:
    """Test get_server_time method."""

    def test_get_server_time_success(self, adapter):
        """Should parse Coinbase time response correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "iso": "2026-03-06T12:00:00Z",
            "epochSeconds": "1741521600",
        }

        with patch.object(adapter.session, "request", return_value=mock_response):
            result = adapter.get_server_time()

            assert isinstance(result, datetime)
            assert result.tzinfo == timezone.utc
            assert result.year == 2026
            assert result.month == 3
            assert result.day == 6

    def test_get_server_time_missing_iso_field(self, adapter):
        """Should raise ExchangeError if 'iso' field is missing."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"epochSeconds": "1741521600"}

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeError, match="Unexpected Coinbase time response"):
                adapter.get_server_time()

    def test_get_server_time_invalid_timestamp(self, adapter):
        """Should raise ExchangeError for invalid timestamp format."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"iso": "invalid-timestamp"}

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeError, match="Failed to parse Coinbase timestamp"):
                adapter.get_server_time()


class TestFetchTicker:
    """Test fetch_ticker method."""

    def test_fetch_ticker_success(self, adapter):
        """Should parse Coinbase ticker response correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "trades": [],
            "best_bid": "50000.00",
            "best_ask": "50001.50",
            "price": "50000.75",
        }

        with patch.object(adapter.session, "request", return_value=mock_response):
            result = adapter.fetch_ticker("BTC-USD")

            assert result["symbol"] == "BTC-USD"
            assert result["bid"] == 50000.00
            assert result["ask"] == 50001.50
            assert result["last"] == 50000.75
            assert isinstance(result["timestamp"], datetime)
            assert result["timestamp"].tzinfo == timezone.utc

    def test_fetch_ticker_missing_fields(self, adapter):
        """Should raise ExchangeError if required fields are missing."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "best_bid": "50000.00",
            # Missing best_ask and price
        }

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeError, match="Missing required fields"):
                adapter.fetch_ticker("BTC-USD")

    def test_fetch_ticker_invalid_price_format(self, adapter):
        """Should raise ExchangeError for non-numeric prices."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "best_bid": "not-a-number",
            "best_ask": "50001.50",
            "price": "50000.75",
        }

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeError, match="Failed to parse numeric values"):
                adapter.fetch_ticker("BTC-USD")

    def test_fetch_ticker_negative_prices(self, adapter):
        """Should raise ExchangeError for negative prices."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "best_bid": "-50000.00",
            "best_ask": "50001.50",
            "price": "50000.75",
        }

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeError, match="Invalid price values"):
                adapter.fetch_ticker("BTC-USD")

    def test_fetch_ticker_zero_prices(self, adapter):
        """Should raise ExchangeError for zero prices."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "best_bid": "0.00",
            "best_ask": "50001.50",
            "price": "50000.75",
        }

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeError, match="Invalid price values"):
                adapter.fetch_ticker("BTC-USD")

    def test_fetch_ticker_inverted_spread(self, adapter):
        """Should raise ExchangeError when bid > ask."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "best_bid": "50002.00",
            "best_ask": "50001.50",
            "price": "50000.75",
        }

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeError, match="Invalid spread.*bid.*ask"):
                adapter.fetch_ticker("BTC-USD")


class TestFetchOrderBook:
    """Test fetch_order_book method."""

    def test_fetch_order_book_success(self, adapter):
        """Should parse Coinbase order book response correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "pricebook": {
                "product_id": "BTC-USD",
                "bids": [
                    {"price": "50000.00", "size": "1.5"},
                    {"price": "49999.00", "size": "2.0"},
                ],
                "asks": [
                    {"price": "50001.00", "size": "1.0"},
                    {"price": "50002.00", "size": "0.5"},
                ],
            }
        }

        with patch.object(adapter.session, "request", return_value=mock_response):
            result = adapter.fetch_order_book("BTC-USD")

            assert "bids" in result
            assert "asks" in result
            assert result["bids"] == [[50000.00, 1.5], [49999.00, 2.0]]
            assert result["asks"] == [[50001.00, 1.0], [50002.00, 0.5]]

    def test_fetch_order_book_empty(self, adapter):
        """Should handle empty order book gracefully."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"pricebook": {"bids": [], "asks": []}}

        with patch.object(adapter.session, "request", return_value=mock_response):
            result = adapter.fetch_order_book("BTC-USD")

            assert result["bids"] == []
            assert result["asks"] == []


class TestFetchFundingRate:
    """Test fetch_funding_rate method."""

    def test_fetch_funding_rate_returns_none(self, adapter):
        """Should return None for spot trading (no funding rates)."""
        result = adapter.fetch_funding_rate("BTC-USD")
        assert result is None


class TestTradingOperations:
    """Test trading operations (not implemented in Sprint 2)."""

    def test_place_order_raises_error(self, adapter):
        """Should raise ExchangeError for place_order."""
        with pytest.raises(ExchangeError, match="not implemented in Sprint 2"):
            adapter.place_order({"symbol": "BTC-USD", "side": "buy"})

    def test_cancel_order_raises_error(self, adapter):
        """Should raise ExchangeError for cancel_order."""
        with pytest.raises(ExchangeError, match="not implemented in Sprint 2"):
            adapter.cancel_order("order-123", "BTC-USD")


class TestErrorHandling:
    """Test error handling for various failure scenarios."""

    def test_rate_limit_error(self, adapter):
        """Should raise ExchangeRateLimitError for 429 response."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_response.headers = {"Retry-After": "60"}
        mock_response.raise_for_status.side_effect = Exception("429")

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeRateLimitError, match="rate limit exceeded"):
                adapter.get_server_time()

    def test_rate_limit_error_includes_retry_after(self, adapter):
        """Should include Retry-After header in error message."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_response.headers = {"Retry-After": "60"}

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeRateLimitError, match="retry after 60s"):
                adapter.get_server_time()

    def test_server_error_5xx(self, adapter):
        """Should raise ExchangeConnectionError for 5xx response."""
        mock_response = Mock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        mock_response.headers = {}

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(
                ExchangeConnectionError, match="Coinbase server error.*503"
            ):
                adapter.get_server_time()

    def test_server_error_500(self, adapter):
        """Should treat 500 errors as transient."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.headers = {}

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(
                ExchangeConnectionError, match="Coinbase server error.*500"
            ):
                adapter.get_server_time()

    def test_http_error_4xx(self, adapter):
        """Should raise ExchangeError for 4xx errors (except 429)."""
        import requests

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeError, match="HTTP error.*404"):
                adapter.get_server_time()

    def test_connection_timeout(self, adapter):
        """Should raise ExchangeConnectionError for timeout."""
        import requests

        with patch.object(
            adapter.session,
            "request",
            side_effect=requests.exceptions.Timeout("Timeout"),
        ):
            with pytest.raises(
                ExchangeConnectionError, match="timeout after 10s"
            ):
                adapter.get_server_time()

    def test_connection_error(self, adapter):
        """Should raise ExchangeConnectionError for connection issues."""
        import requests

        with patch.object(
            adapter.session,
            "request",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        ):
            with pytest.raises(
                ExchangeConnectionError, match="connection error.*check network"
            ):
                adapter.get_server_time()

    def test_invalid_json_response(self, adapter):
        """Should raise ExchangeError for invalid JSON."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeError, match="Invalid JSON response"):
                adapter.get_server_time()

    def test_truncates_long_error_messages(self, adapter):
        """Should truncate very long error responses."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "x" * 1000  # Very long message
        mock_response.headers = {}

        with patch.object(adapter.session, "request", return_value=mock_response):
            with pytest.raises(ExchangeRateLimitError) as exc_info:
                adapter.get_server_time()
            # Should be truncated to 200 chars
            assert len(exc_info.value.args[0]) < 300


class TestFactoryIntegration:
    """Test that Coinbase adapter is registered in factory."""

    def test_factory_returns_coinbase_adapter(self):
        """Factory should return CoinbaseAdapter for 'coinbase' exchange name."""
        from core.exchange.factory import get_exchange_adapter

        adapter = get_exchange_adapter("coinbase")
        assert isinstance(adapter, CoinbaseAdapter)
        assert adapter.name == "coinbase"

    def test_factory_case_insensitive(self):
        """Factory should handle case-insensitive exchange names."""
        from core.exchange.factory import get_exchange_adapter

        adapter1 = get_exchange_adapter("Coinbase")
        adapter2 = get_exchange_adapter("COINBASE")
        adapter3 = get_exchange_adapter("coinbase")

        assert all(isinstance(a, CoinbaseAdapter) for a in [adapter1, adapter2, adapter3])
