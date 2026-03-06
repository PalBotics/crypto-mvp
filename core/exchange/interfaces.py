"""Exchange adapter interface definitions.

Defines the standard interface that all exchange adapters must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class ExchangeAdapter(ABC):
    """Base interface for exchange integrations.

    All exchange adapters (mock, Coinbase, etc.) must implement these methods
    to provide a consistent interface for market data collection and trading.
    """

    name: str  # Exchange identifier (e.g., "coinbase", "mock")

    @abstractmethod
    def get_server_time(self) -> datetime:
        """Get exchange server time.

        Returns:
            Timezone-aware datetime in UTC
        """

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch current ticker data for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD")

        Returns:
            Dictionary with keys: symbol, bid, ask, last, timestamp
        """

    @abstractmethod
    def fetch_order_book(self, symbol: str) -> dict[str, Any]:
        """Fetch order book for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD")

        Returns:
            Dictionary with keys: bids, asks (each as list of [price, size])
        """

    @abstractmethod
    def fetch_funding_rate(self, symbol: str) -> dict[str, Any] | None:
        """Fetch funding rate for a perpetual futures symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Funding rate data or None if not applicable
        """

    @abstractmethod
    def place_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Place an order on the exchange.

        Args:
            order: Order parameters

        Returns:
            Order placement response with order_id and status
        """

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an existing order on the exchange.

        Args:
            order_id: Exchange order ID
            symbol: Trading pair symbol

        Returns:
            True if cancellation successful
        """