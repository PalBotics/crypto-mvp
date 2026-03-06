"""Coinbase Advanced Trade API adapter for market data collection.

Uses public Coinbase REST endpoints for market data.
No authentication required for the implemented Sprint 2 methods.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from core.exchange.exceptions import (
    ExchangeConnectionError,
    ExchangeError,
    ExchangeRateLimitError,
)
from core.exchange.interfaces import ExchangeAdapter


class CoinbaseAdapter(ExchangeAdapter):
    """Adapter for Coinbase Advanced Trade API.

    Sprint 2 implementation focuses on public market data endpoints.
    Trading operations (place_order, cancel_order) are not yet implemented.
    """

    name = "coinbase"

    # Coinbase Advanced Trade API base URL
    BASE_URL = "https://api.coinbase.com/api/v3/brokerage"

    # Request timeout in seconds
    TIMEOUT = 10

    # Maximum error message length in logs (truncate long responses)
    MAX_ERROR_MESSAGE_LENGTH = 200

    def __init__(self) -> None:
        """Initialize Coinbase adapter with default session."""
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "crypto-mvp/0.1.0",
            }
        )

    def _make_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Make HTTP request to Coinbase API with error handling.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path relative to BASE_URL
            **kwargs: Additional arguments passed to requests

        Returns:
            Response JSON as dict

        Raises:
            ExchangeConnectionError: Network or connection issues
            ExchangeRateLimitError: Rate limit exceeded
            ExchangeError: Other API errors
        """
        url = f"{self.BASE_URL}{path}"

        # Ensure explicit timeout is always set
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.TIMEOUT

        try:
            response = self.session.request(method, url, **kwargs)

            # Handle rate limiting
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                raise ExchangeRateLimitError(
                    f"Coinbase rate limit exceeded (retry after {retry_after}s): {response.text[:self.MAX_ERROR_MESSAGE_LENGTH]}"
                )

            # Handle server errors (5xx) - these are transient
            if 500 <= response.status_code < 600:
                raise ExchangeConnectionError(
                    f"Coinbase server error (HTTP {response.status_code}): {response.text[:self.MAX_ERROR_MESSAGE_LENGTH]}"
                )

            # Raise for other HTTP errors (4xx except 429)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.Timeout as exc:
            raise ExchangeConnectionError(
                f"Coinbase API request timeout after {kwargs['timeout']}s: {url}"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise ExchangeConnectionError(
                f"Coinbase API connection error (check network): {url}"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            # Catch 4xx errors not handled above
            raise ExchangeError(
                f"Coinbase API HTTP error: {exc.response.status_code} - {exc.response.text[:self.MAX_ERROR_MESSAGE_LENGTH]}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ExchangeError(f"Coinbase API request failed: {exc}") from exc
        except ValueError as exc:
            # JSON decode error
            raise ExchangeError(
                f"Invalid JSON response from Coinbase at {url}: {exc}"
            ) from exc

    def get_server_time(self) -> datetime:
        """Get Coinbase server time.

        Returns:
            Timezone-aware datetime in UTC

        Raises:
            ExchangeError: If request fails or response is invalid
        """
        data = self._make_request("GET", "/time")

        # Coinbase returns: {"iso": "2023-01-01T00:00:00Z", "epochSeconds": "1672531200"}
        if "iso" not in data:
            raise ExchangeError(f"Unexpected Coinbase time response: {data}")

        try:
            # Parse ISO 8601 timestamp
            dt = datetime.fromisoformat(data["iso"].replace("Z", "+00:00"))
            # Ensure UTC timezone
            return dt.astimezone(timezone.utc)
        except (ValueError, AttributeError) as exc:
            raise ExchangeError(
                f"Failed to parse Coinbase timestamp '{data.get('iso')}': {exc}"
            ) from exc

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch current ticker data for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD")

        Returns:
            Dictionary with keys: symbol, bid, ask, last, timestamp

        Raises:
            ExchangeError: If request fails or response is invalid
        """
        # Coinbase uses product_id format like "BTC-USD"
        product_id = symbol

        data = self._make_request("GET", f"/market/products/{product_id}/ticker")

        # Coinbase ticker response structure:
        # {
        #   "trades": [...],
        #   "best_bid": "50000.00",
        #   "best_ask": "50001.00",
        #   "price": "50000.50"
        # }

        try:
            best_bid = data.get("best_bid")
            best_ask = data.get("best_ask")
            price = data.get("price")

            # Validate required fields exist
            if best_bid is None or best_ask is None or price is None:
                raise ExchangeError(
                    f"Missing required fields in Coinbase ticker for {symbol}. "
                    f"Got: best_bid={best_bid}, best_ask={best_ask}, price={price}"
                )

            # Convert string prices to float with validation
            bid = float(best_bid)
            ask = float(best_ask)
            last = float(price)

            # Validate numeric values are sensible
            if bid <= 0 or ask <= 0 or last <= 0:
                raise ExchangeError(
                    f"Invalid price values for {symbol}: bid={bid}, ask={ask}, last={last}"
                )

            if bid > ask:
                raise ExchangeError(
                    f"Invalid spread for {symbol}: bid={bid} > ask={ask}"
                )

            # Get current timestamp (Coinbase ticker doesn't include timestamp)
            timestamp = datetime.now(timezone.utc)

            return {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "last": last,
                "timestamp": timestamp,
            }

        except ValueError as exc:
            # Catch float conversion errors specifically
            raise ExchangeError(
                f"Failed to parse numeric values in Coinbase ticker for {symbol}: {exc}"
            ) from exc
        except (TypeError, KeyError) as exc:
            raise ExchangeError(
                f"Unexpected ticker response structure for {symbol}: {exc}"
            ) from exc

    def fetch_order_book(self, symbol: str) -> dict[str, Any]:
        """Fetch order book for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD")

        Returns:
            Dictionary with keys: bids, asks (each as list of [price, size])

        Raises:
            ExchangeError: If request fails or response is invalid

        Note:
            Minimal implementation for Sprint 2. Returns limited depth.
        """
        product_id = symbol

        # Coinbase order book endpoint with limit parameter
        params = {"limit": 10}
        data = self._make_request(
            "GET", f"/market/products/{product_id}/book", params=params
        )

        # Coinbase returns: {"pricebook": {"product_id": "...", "bids": [...], "asks": [...]}}
        try:
            pricebook = data.get("pricebook", {})
            bids = pricebook.get("bids", [])
            asks = pricebook.get("asks", [])

            # Convert from Coinbase format [{"price": "50000", "size": "1.5"}, ...]
            # to simplified format [[50000.0, 1.5], ...]
            formatted_bids = []
            for bid in bids:
                formatted_bids.append([float(bid["price"]), float(bid["size"])])

            formatted_asks = []
            for ask in asks:
                formatted_asks.append([float(ask["price"]), float(ask["size"])])

            return {
                "bids": formatted_bids,
                "asks": formatted_asks,
            }

        except (ValueError, TypeError, KeyError) as exc:
            raise ExchangeError(
                f"Failed to parse Coinbase order book for {symbol}: {exc}"
            ) from exc

    def fetch_funding_rate(self, symbol: str) -> dict[str, Any] | None:
        """Fetch funding rate for a perpetual futures symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            None - Coinbase spot trading does not have funding rates

        Note:
            Coinbase primarily offers spot trading. Funding rates are only
            relevant for perpetual futures contracts. This method returns None
            to indicate funding rates are not applicable.
        """
        return None

    def place_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Place an order on Coinbase.

        Args:
            order: Order parameters

        Raises:
            ExchangeError: Always raises - not implemented in Sprint 2

        Note:
            Order execution is out of scope for Sprint 2 (market data collection).
            Authentication and order placement will be implemented in a future sprint.
        """
        raise ExchangeError(
            "Order placement not implemented in Sprint 2. "
            "Coinbase trading operations require authentication and are planned for a future sprint."
        )

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an existing order on Coinbase.

        Args:
            order_id: Exchange order ID
            symbol: Trading pair symbol

        Raises:
            ExchangeError: Always raises - not implemented in Sprint 2

        Note:
            Order cancellation is out of scope for Sprint 2 (market data collection).
            Authentication and order management will be implemented in a future sprint.
        """
        raise ExchangeError(
            "Order cancellation not implemented in Sprint 2. "
            "Coinbase trading operations require authentication and are planned for a future sprint."
        )
