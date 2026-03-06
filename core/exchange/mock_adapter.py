"""Mock exchange adapter for testing and development.

Generates synthetic market data without requiring actual exchange connectivity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from random import random
from typing import Any

from core.exchange.interfaces import ExchangeAdapter


class MockExchangeAdapter(ExchangeAdapter):
    """Mock exchange adapter for testing and development.

    Returns synthetic market data with randomized prices around a baseline.
    No network calls or authentication required.
    """

    name = "mock"

    def get_server_time(self) -> datetime:
        """Get current UTC time as mock server time."""
        return datetime.now(timezone.utc)

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Generate synthetic ticker data.

        Args:
            symbol: Trading pair symbol (ignored, but returned in response)

        Returns:
            Dictionary with symbol, bid, ask, last, timestamp
        """
        price = 50000 + random() * 1000

        return {
            "symbol": symbol,
            "bid": price - 1,
            "ask": price + 1,
            "last": price,
            "timestamp": datetime.now(timezone.utc),
        }

    def fetch_order_book(self, symbol: str) -> dict[str, Any]:
        """Generate synthetic order book data.

        Args:
            symbol: Trading pair symbol (ignored)

        Returns:
            Dictionary with bids and asks lists
        """
        price = 50000 + random() * 1000

        return {
            "bids": [[price - 1, 1]],
            "asks": [[price + 1, 1]],
        }

    def fetch_funding_rate(self, symbol: str) -> dict[str, Any] | None:
        """Return None as mock exchange has no funding rates.

        Args:
            symbol: Trading pair symbol (ignored)

        Returns:
            None
        """
        return None

    def place_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Mock order placement (always succeeds).

        Args:
            order: Order parameters (ignored)

        Returns:
            Dictionary with mock order_id and status
        """
        return {
            "order_id": "mock-order-1",
            "status": "filled",
        }

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Mock order cancellation (always succeeds).

        Args:
            order_id: Exchange order ID (ignored)
            symbol: Trading pair symbol (ignored)

        Returns:
            True
        """
        return True