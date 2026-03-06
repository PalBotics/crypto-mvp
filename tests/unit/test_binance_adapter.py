"""Unit tests for BinanceAdapter.

Tests use mocked HTTP responses to avoid external API calls.
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from core.exchange.binance_adapter import BinanceAdapter
from core.exchange.exceptions import (
    ExchangeConnectionError,
    ExchangeError,
    ExchangeRateLimitError,
)


@pytest.fixture
def adapter() -> BinanceAdapter:
    """Create a BinanceAdapter instance for testing."""
    return BinanceAdapter()


def test_fetch_funding_rate_success_parses_response(adapter: BinanceAdapter) -> None:
    """Should normalize Binance funding response into expected payload shape."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "symbol": "BTCUSDT",
            "fundingRate": "0.00010000",
            "fundingTime": 1741521600000,
            "markPrice": "63123.45",
        }
    ]

    with patch.object(adapter.session, "request", return_value=mock_response):
        result = adapter.fetch_funding_rate("BTCUSDT")

    assert result is not None
    assert result["symbol"] == "BTCUSDT"
    assert result["exchange_symbol"] == "BTCUSDT"
    assert result["funding_rate"] == 0.0001
    assert result["funding_interval_hours"] == 8
    assert result["predicted_funding_rate"] is None
    assert result["mark_price"] == 63123.45
    assert result["index_price"] is None
    assert result["next_funding_ts"] is None
    assert isinstance(result["event_ts"], datetime)
    assert result["event_ts"].tzinfo == timezone.utc


def test_fetch_funding_rate_converts_timestamp_ms_to_utc(adapter: BinanceAdapter) -> None:
    """Funding timestamp should be converted from epoch milliseconds to UTC datetime."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "symbol": "ETHUSDT",
            "fundingRate": "0.00005000",
            "fundingTime": 1700000000000,
        }
    ]

    with patch.object(adapter.session, "request", return_value=mock_response):
        result = adapter.fetch_funding_rate("ETHUSDT")

    assert result is not None
    expected = datetime.fromtimestamp(1700000000000 / 1000, tz=timezone.utc)
    assert result["event_ts"] == expected


def test_fetch_funding_rate_returns_none_when_no_rows(adapter: BinanceAdapter) -> None:
    """Should return None when Binance returns an empty funding history list."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = []

    with patch.object(adapter.session, "request", return_value=mock_response):
        result = adapter.fetch_funding_rate("BTCUSDT")

    assert result is None


def test_fetch_funding_rate_missing_fields_raises_exchange_error(
    adapter: BinanceAdapter,
) -> None:
    """Should raise ExchangeError if required funding fields are missing."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "symbol": "BTCUSDT",
            # fundingRate missing
            "fundingTime": 1741521600000,
        }
    ]

    with patch.object(adapter.session, "request", return_value=mock_response):
        with pytest.raises(ExchangeError, match="Missing required fields"):
            adapter.fetch_funding_rate("BTCUSDT")


def test_rate_limit_error_translated(adapter: BinanceAdapter) -> None:
    """Should raise ExchangeRateLimitError for 429 responses."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.text = "Rate limit exceeded"
    mock_response.headers = {"Retry-After": "60"}

    with patch.object(adapter.session, "request", return_value=mock_response):
        with pytest.raises(ExchangeRateLimitError, match="rate limit exceeded"):
            adapter.fetch_funding_rate("BTCUSDT")


def test_server_error_translated(adapter: BinanceAdapter) -> None:
    """Should raise ExchangeConnectionError for 5xx responses."""
    mock_response = Mock()
    mock_response.status_code = 503
    mock_response.text = "Service Unavailable"
    mock_response.headers = {}

    with patch.object(adapter.session, "request", return_value=mock_response):
        with pytest.raises(ExchangeConnectionError, match="server error.*503"):
            adapter.fetch_funding_rate("BTCUSDT")


def test_http_error_translated_to_exchange_error(adapter: BinanceAdapter) -> None:
    """Should raise ExchangeError for 4xx responses (except 429)."""
    import requests

    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=mock_response
    )

    with patch.object(adapter.session, "request", return_value=mock_response):
        with pytest.raises(ExchangeError, match="HTTP error.*404"):
            adapter.fetch_funding_rate("BTCUSDT")
