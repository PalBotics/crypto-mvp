"""Binance Futures API adapter for funding-rate and ticker collection.

Uses public Binance USD-M Futures REST endpoints.
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


class BinanceAdapter(ExchangeAdapter):
    """Adapter for Binance USD-M Futures public endpoints."""

    name = "binance"

    # Binance USD-M Futures API base URL
    BASE_URL = "https://fapi.binance.com"

    # Request timeout in seconds
    TIMEOUT = 10

    # Maximum error message length in logs (truncate long responses)
    MAX_ERROR_MESSAGE_LENGTH = 200

    def __init__(self) -> None:
        """Initialize Binance adapter with default session."""
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "crypto-mvp/0.1.0",
            }
        )

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize common symbol formats to Binance Futures style."""
        return symbol.replace("-", "").replace("/", "").upper()

    def _make_request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make HTTP request to Binance API with consistent error handling."""
        url = f"{self.BASE_URL}{path}"

        if "timeout" not in kwargs:
            kwargs["timeout"] = self.TIMEOUT

        try:
            response = self.session.request(method, url, **kwargs)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                raise ExchangeRateLimitError(
                    f"Binance rate limit exceeded (retry after {retry_after}s): {response.text[:self.MAX_ERROR_MESSAGE_LENGTH]}"
                )

            if 500 <= response.status_code < 600:
                raise ExchangeConnectionError(
                    f"Binance server error (HTTP {response.status_code}): {response.text[:self.MAX_ERROR_MESSAGE_LENGTH]}"
                )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout as exc:
            raise ExchangeConnectionError(
                f"Binance API request timeout after {kwargs['timeout']}s: {url}"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise ExchangeConnectionError(
                f"Binance API connection error (check network): {url}"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            raise ExchangeError(
                f"Binance API HTTP error: {exc.response.status_code} - {exc.response.text[:self.MAX_ERROR_MESSAGE_LENGTH]}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ExchangeError(f"Binance API request failed: {exc}") from exc
        except ValueError as exc:
            raise ExchangeError(f"Invalid JSON response from Binance at {url}: {exc}") from exc

    def get_server_time(self) -> datetime:
        """Get Binance server time as timezone-aware UTC datetime."""
        data = self._make_request("GET", "/fapi/v1/time")

        server_time_ms = data.get("serverTime")
        if server_time_ms is None:
            raise ExchangeError(f"Unexpected Binance time response: {data}")

        try:
            return datetime.fromtimestamp(float(server_time_ms) / 1000, tz=timezone.utc)
        except (ValueError, TypeError) as exc:
            raise ExchangeError(
                f"Failed to parse Binance server time '{server_time_ms}': {exc}"
            ) from exc

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch current ticker data for a symbol using 24hr ticker endpoint."""
        exchange_symbol = self._normalize_symbol(symbol)
        data = self._make_request(
            "GET", "/fapi/v1/ticker/24hr", params={"symbol": exchange_symbol}
        )

        try:
            bid = float(data["bidPrice"])
            ask = float(data["askPrice"])
            last = float(data["lastPrice"])

            if bid <= 0 or ask <= 0 or last <= 0:
                raise ExchangeError(
                    f"Invalid price values for {symbol}: bid={bid}, ask={ask}, last={last}"
                )

            if bid > ask:
                raise ExchangeError(
                    f"Invalid spread for {symbol}: bid={bid} > ask={ask}"
                )

            return {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "last": last,
                "timestamp": datetime.now(timezone.utc),
            }

        except KeyError as exc:
            raise ExchangeError(
                f"Missing required fields in Binance ticker for {symbol}: {exc}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ExchangeError(
                f"Failed to parse numeric values in Binance ticker for {symbol}: {exc}"
            ) from exc

    def fetch_order_book(self, symbol: str) -> dict[str, Any]:
        """Fetch order book for a symbol."""
        exchange_symbol = self._normalize_symbol(symbol)
        data = self._make_request(
            "GET",
            "/fapi/v1/depth",
            params={"symbol": exchange_symbol, "limit": 10},
        )

        try:
            bids = [[float(level[0]), float(level[1])] for level in data.get("bids", [])]
            asks = [[float(level[0]), float(level[1])] for level in data.get("asks", [])]
            return {"bids": bids, "asks": asks}
        except (TypeError, ValueError, IndexError) as exc:
            raise ExchangeError(
                f"Failed to parse Binance order book for {symbol}: {exc}"
            ) from exc

    def fetch_funding_rate(self, symbol: str) -> dict[str, Any] | None:
        """Fetch latest funding rate for a perpetual futures symbol."""
        exchange_symbol = self._normalize_symbol(symbol)
        data = self._make_request(
            "GET",
            "/fapi/v1/fundingRate",
            params={"symbol": exchange_symbol, "limit": 1},
        )

        if not isinstance(data, list) or not data:
            return None

        latest = data[-1]

        try:
            event_ts = datetime.fromtimestamp(
                float(latest["fundingTime"]) / 1000,
                tz=timezone.utc,
            )
            funding_rate = float(latest["fundingRate"])

            mark_price_raw = latest.get("markPrice")
            mark_price = float(mark_price_raw) if mark_price_raw is not None else None

            return {
                "symbol": symbol,
                "exchange_symbol": exchange_symbol,
                "funding_rate": funding_rate,
                "funding_interval_hours": 8,
                "predicted_funding_rate": None,
                "mark_price": mark_price,
                "index_price": None,
                "next_funding_ts": None,
                "event_ts": event_ts,
            }

        except KeyError as exc:
            raise ExchangeError(
                f"Missing required fields in Binance funding rate for {symbol}: {exc}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ExchangeError(
                f"Failed to parse Binance funding rate for {symbol}: {exc}"
            ) from exc

    def place_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Place an order on Binance.

        Note:
            Order execution is out of scope for Sprint 3 adapter bootstrap.
        """
        raise ExchangeError(
            "Order placement not implemented in Sprint 3. "
            "Binance trading operations require authentication and are planned for a future sprint."
        )

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an existing order on Binance.

        Note:
            Order cancellation is out of scope for Sprint 3 adapter bootstrap.
        """
        raise ExchangeError(
            "Order cancellation not implemented in Sprint 3. "
            "Binance trading operations require authentication and are planned for a future sprint."
        )
