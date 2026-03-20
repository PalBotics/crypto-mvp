from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick
from core.utils.logging import get_logger

_log = get_logger(__name__)

try:
    from coinbase.rest import RESTClient as CoinbaseRESTClient
except Exception:  # pragma: no cover - import outcome depends on installed extras
    CoinbaseRESTClient = None  # type: ignore[assignment]


class CoinbaseAdvancedAdapter:
    """Coinbase Advanced REST adapter for ETH perpetual market + funding snapshots."""

    name = "coinbase_advanced"

    def __init__(
        self,
        *,
        api_key: str,
        private_key: str,
        timeout_seconds: int = 10,
        base_url: str = "https://api.coinbase.com",
        adapter_name: str = "coinbase_advanced",
        exchange: str = "coinbase_advanced",
        symbol: str = "ETH-PERP",
        product_id: str = "ETH-PERP-INTX",
    ) -> None:
        self._api_key = api_key.strip()
        self._private_key = private_key.strip()
        self._timeout_seconds = timeout_seconds
        self._base_url = base_url.rstrip("/")
        self._adapter_name = adapter_name
        self._exchange = exchange
        self._symbol = symbol
        self._product_id = product_id

        self._disabled = not (self._api_key and self._private_key)
        self._sdk_client: Any | None = None

        if self._disabled:
            _log.info(
                "coinbase_adapter_disabled",
                exchange=self._exchange,
                reason="missing_credentials",
            )
            return

        if CoinbaseRESTClient is not None:
            self._sdk_client = CoinbaseRESTClient(
                api_key=self._api_key,
                api_secret=self._private_key,
                timeout=timeout_seconds,
            )
            _log.info("coinbase_sdk_enabled", exchange=self._exchange)
        else:
            _log.warning(
                "coinbase_sdk_unavailable_using_http_fallback",
                exchange=self._exchange,
            )

    @property
    def is_enabled(self) -> bool:
        return not self._disabled

    @property
    def product_id(self) -> str:
        return self._product_id

    def get_ticker(self, symbol: str) -> MarketTick | None:
        if self._disabled:
            return None

        product = self._get_product_with_retry()
        if product is None:
            return None

        bid = self._safe_decimal(
            product,
            ["best_bid"],
            field_name="best_bid",
            expected_missing=True,
        )
        ask = self._safe_decimal(
            product,
            ["best_ask"],
            field_name="best_ask",
            expected_missing=True,
        )
        if bid is None or ask is None:
            top_of_book = self._get_top_of_book_with_retry()
            if top_of_book is not None:
                bid = top_of_book.get("bid")
                ask = top_of_book.get("ask")

        mark = self._safe_decimal(
            product,
            ["future_product_details", "perpetual_details", "mark_price"],
            field_name="future_product_details.perpetual_details.mark_price",
            expected_missing=True,
        )
        if mark is None:
            mark = self._safe_decimal(
                product,
                ["future_product_details", "mark_price"],
                field_name="future_product_details.mark_price",
                expected_missing=True,
            )

        last = self._safe_decimal(product, ["price"], field_name="price")

        if bid is None or ask is None:
            _log.warning(
                "coinbase_ticker_missing_top_of_book",
                exchange=self._exchange,
                symbol=symbol,
                product_id=self._product_id,
            )
            return None

        mid = mark if mark is not None else (bid + ask) / Decimal("2")
        now_utc = datetime.now(timezone.utc)

        return MarketTick(
            exchange=self._exchange,
            adapter_name=self._adapter_name,
            symbol=symbol,
            exchange_symbol=self._product_id,
            bid_price=bid,
            ask_price=ask,
            mid_price=mid,
            last_price=last,
            bid_size=None,
            ask_size=None,
            event_ts=now_utc,
            ingested_ts=now_utc,
            sequence_id=None,
        )

    def get_funding_rate(self, symbol: str) -> FundingRateSnapshot | None:
        if self._disabled:
            return None

        product = self._get_product_with_retry()
        if product is None:
            return None

        # Coinbase product payload exposes perpetual funding rates in decimal
        # fraction form for the funding interval (hourly for INTX perps).
        funding_rate = self._safe_decimal(
            product,
            ["future_product_details", "perpetual_details", "funding_rate"],
            field_name="future_product_details.perpetual_details.funding_rate",
        )
        if funding_rate is None:
            funding_rate = self._safe_decimal(
                product,
                ["future_product_details", "perpetual_details", "fundingRate"],
                field_name="future_product_details.perpetual_details.fundingRate",
            )
        if funding_rate is None:
            funding_rate = self._safe_decimal(
                product,
                ["future_product_details", "funding_rate"],
                field_name="future_product_details.funding_rate",
            )
        if funding_rate is None:
            funding_rate = self._safe_decimal(
                product,
                ["future_product_details", "fundingRate"],
                field_name="future_product_details.fundingRate",
            )

        if funding_rate is None:
            _log.warning(
                "coinbase_funding_missing_rate",
                exchange=self._exchange,
                symbol=symbol,
                product_id=self._product_id,
            )
            return None

        predicted_funding_rate = self._safe_decimal(
            product,
            ["future_product_details", "perpetual_details", "next_funding_rate"],
            field_name="future_product_details.perpetual_details.next_funding_rate",
            expected_missing=True,
        )
        if predicted_funding_rate is None:
            predicted_funding_rate = self._safe_decimal(
                product,
                ["future_product_details", "next_funding_rate"],
                field_name="future_product_details.next_funding_rate",
                expected_missing=True,
            )

        mark_price = self._safe_decimal(
            product,
            ["future_product_details", "perpetual_details", "mark_price"],
            field_name="future_product_details.perpetual_details.mark_price",
            expected_missing=True,
        )
        if mark_price is None:
            mark_price = self._safe_decimal(
                product,
                ["future_product_details", "mark_price"],
                field_name="future_product_details.mark_price",
                expected_missing=True,
            )

        next_funding_ts = self._parse_iso(
            self._safe_str(
                product,
                ["future_product_details", "perpetual_details", "funding_time"],
            )
        )
        if next_funding_ts is None:
            next_funding_ts = self._parse_iso(
                self._safe_str(product, ["future_product_details", "funding_time"])
            )
        if next_funding_ts is None:
            next_funding_ts = self._next_settlement_utc()

        now_utc = datetime.now(timezone.utc)

        return FundingRateSnapshot(
            exchange=self._exchange,
            adapter_name=self._adapter_name,
            symbol=symbol,
            exchange_symbol=self._product_id,
            funding_rate=funding_rate,
            funding_interval_hours=1,
            predicted_funding_rate=predicted_funding_rate,
            mark_price=mark_price,
            index_price=None,
            next_funding_ts=next_funding_ts,
            event_ts=now_utc,
            ingested_ts=now_utc,
        )

    def get_public_product(self, product_id: str | None = None) -> dict[str, Any] | None:
        target_product = (product_id or self._product_id).strip()
        url = f"{self._base_url}/api/v3/brokerage/market/products/{target_product}"

        try:
            response = httpx.get(url, timeout=self._timeout_seconds)
        except httpx.TimeoutException:
            return None
        except httpx.HTTPError:
            return None

        if response.status_code != 200:
            return None

        payload = response.json()
        if not isinstance(payload, dict):
            return None
        return payload

    def get_public_ticker(self, product_id: str | None = None) -> dict[str, Decimal | str] | None:
        target_product = (product_id or self._product_id).strip()
        payload = self.get_public_product(product_id=target_product)
        if payload is None:
            return None

        bid = self._safe_decimal(payload, ["best_bid"], field_name="best_bid", expected_missing=True)
        ask = self._safe_decimal(payload, ["best_ask"], field_name="best_ask", expected_missing=True)
        if bid is None or ask is None:
            original_product = self._product_id
            try:
                self._product_id = target_product
                top_of_book = self._get_top_of_book_with_retry()
            finally:
                self._product_id = original_product

            if top_of_book is not None:
                bid = top_of_book.get("bid")
                ask = top_of_book.get("ask")

        last = self._safe_decimal(payload, ["price"], field_name="price", expected_missing=True)

        mark = self._safe_decimal(
            payload,
            ["future_product_details", "perpetual_details", "mark_price"],
            field_name="future_product_details.perpetual_details.mark_price",
            expected_missing=True,
        )
        if mark is None:
            mark = self._safe_decimal(
                payload,
                ["future_product_details", "mark_price"],
                field_name="future_product_details.mark_price",
                expected_missing=True,
            )

        if bid is None or ask is None:
            return None

        if last is None:
            last = mark if mark is not None else (bid + ask) / Decimal("2")

        return {
            "product_id": str(payload.get("product_id") or target_product),
            "bid": bid,
            "ask": ask,
            "last": last,
            "mark": mark,
        }

    def get_public_funding_rate(self, product_id: str | None = None) -> dict[str, Decimal | int] | None:
        payload = self.get_public_product(product_id=product_id)
        if payload is None:
            return None

        funding_rate = self._safe_decimal(
            payload,
            ["future_product_details", "perpetual_details", "funding_rate"],
            field_name="future_product_details.perpetual_details.funding_rate",
            expected_missing=True,
        )
        if funding_rate is None:
            funding_rate = self._safe_decimal(
                payload,
                ["future_product_details", "funding_rate"],
                field_name="future_product_details.funding_rate",
                expected_missing=True,
            )
        if funding_rate is None:
            return None

        return {
            "funding_rate": funding_rate,
            "funding_interval_hours": 1,
        }

    def _get_product_with_retry(self) -> dict[str, Any] | None:
        attempts = 2
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return self._get_product()
            except Exception as exc:
                last_error = exc
                _log.warning(
                    "coinbase_request_retry",
                    exchange=self._exchange,
                    product_id=self._product_id,
                    attempt=attempt,
                    max_attempts=attempts,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        _log.error(
            "coinbase_request_failed",
            exchange=self._exchange,
            product_id=self._product_id,
            error=str(last_error) if last_error else "unknown",
            error_type=type(last_error).__name__ if last_error else "UnknownError",
        )
        return None

    def _get_top_of_book_with_retry(self) -> dict[str, Decimal] | None:
        attempts = 2
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return self._get_top_of_book()
            except Exception as exc:
                last_error = exc
                _log.warning(
                    "coinbase_top_of_book_retry",
                    exchange=self._exchange,
                    product_id=self._product_id,
                    attempt=attempt,
                    max_attempts=attempts,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        _log.error(
            "coinbase_top_of_book_failed",
            exchange=self._exchange,
            product_id=self._product_id,
            error=str(last_error) if last_error else "unknown",
            error_type=type(last_error).__name__ if last_error else "UnknownError",
        )
        return None

    def _get_top_of_book(self) -> dict[str, Decimal]:
        if self._sdk_client is not None:
            response = self._sdk_client.get_best_bid_ask(product_ids=[self._product_id])
            payload = self._to_dict(response)
            if not isinstance(payload, dict):
                raise RuntimeError("Coinbase SDK returned non-dict top-of-book payload")
            return self._extract_top_of_book(payload)

        url = f"{self._base_url}/api/v3/brokerage/market/product_book"
        try:
            response = httpx.get(
                url,
                params={"product_id": self._product_id, "limit": 1},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError("Coinbase top-of-book request timed out") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Coinbase top-of-book HTTP transport error") from exc

        if response.status_code != 200:
            raise RuntimeError(f"Coinbase top-of-book HTTP status {response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Coinbase top-of-book payload is not a dict")
        return self._extract_top_of_book(payload)

    def _extract_top_of_book(self, payload: dict[str, Any]) -> dict[str, Decimal]:
        # SDK shape: {"pricebooks": [{"bids": [...], "asks": [...]}]}
        pricebooks = payload.get("pricebooks")
        if isinstance(pricebooks, list) and pricebooks:
            first = pricebooks[0]
            if isinstance(first, dict):
                return self._extract_bid_ask_from_book(first)

        # REST public product_book shape: {"pricebook": {"bids": [...], "asks": [...]}}
        pricebook = payload.get("pricebook")
        if isinstance(pricebook, dict):
            return self._extract_bid_ask_from_book(pricebook)

        raise RuntimeError("Coinbase top-of-book payload missing bids/asks")

    def _extract_bid_ask_from_book(self, book: dict[str, Any]) -> dict[str, Decimal]:
        bids = book.get("bids")
        asks = book.get("asks")
        if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
            raise RuntimeError("Coinbase top-of-book missing bid/ask levels")

        bid = self._safe_decimal_from_level(bids[0], "bid")
        ask = self._safe_decimal_from_level(asks[0], "ask")
        return {"bid": bid, "ask": ask}

    def _safe_decimal_from_level(self, level: Any, side: str) -> Decimal:
        if isinstance(level, dict):
            value = level.get("price")
        elif isinstance(level, list) and level:
            value = level[0]
        else:
            value = None

        if value is None:
            raise RuntimeError(f"Coinbase top-of-book {side} price missing")

        try:
            return Decimal(str(value))
        except Exception as exc:
            raise RuntimeError(f"Coinbase top-of-book {side} price invalid") from exc

    def _get_product(self) -> dict[str, Any]:
        if self._sdk_client is not None:
            response = self._sdk_client.get_product(product_id=self._product_id)
            payload = self._to_dict(response)
            if not isinstance(payload, dict):
                raise RuntimeError("Coinbase SDK returned non-dict payload")
            _log.debug(
                "coinbase_product_payload",
                exchange=self._exchange,
                product_id=self._product_id,
                payload=payload,
            )
            return payload

        return self._get_product_via_rest()

    def _get_product_via_rest(self) -> dict[str, Any]:
        # Public endpoint fallback for environments without SDK.
        url = f"{self._base_url}/api/v3/brokerage/market/products/{self._product_id}"
        try:
            response = httpx.get(url, timeout=self._timeout_seconds)
        except httpx.TimeoutException as exc:
            raise RuntimeError("Coinbase request timed out") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Coinbase HTTP transport error") from exc

        if response.status_code != 200:
            raise RuntimeError(f"Coinbase HTTP status {response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Coinbase payload is not a dict")
        _log.debug(
            "coinbase_product_payload",
            exchange=self._exchange,
            product_id=self._product_id,
            payload=payload,
        )
        return payload

    def _to_dict(self, response: Any) -> Any:
        if hasattr(response, "to_dict"):
            return response.to_dict()
        if isinstance(response, dict):
            return response
        if hasattr(response, "__dict__"):
            return dict(response.__dict__)
        return response

    def _safe_decimal(
        self,
        payload: dict[str, Any],
        path: list[str],
        *,
        field_name: str,
        expected_missing: bool = False,
    ) -> Decimal | None:
        value = self._resolve_path(payload, path)
        if value is None or value == "":
            if expected_missing:
                _log.debug(
                    "coinbase_field_missing",
                    exchange=self._exchange,
                    product_id=self._product_id,
                    field=field_name,
                )
            else:
                _log.warning(
                    "coinbase_field_missing",
                    exchange=self._exchange,
                    product_id=self._product_id,
                    field=field_name,
                )
            return None

        try:
            return Decimal(str(value))
        except Exception:
            _log.warning(
                "coinbase_field_invalid_decimal",
                exchange=self._exchange,
                product_id=self._product_id,
                field=field_name,
                value=str(value),
            )
            return None

    def _safe_str(self, payload: dict[str, Any], path: list[str]) -> str | None:
        value = self._resolve_path(payload, path)
        if value is None:
            return None
        return str(value)

    def _resolve_path(self, payload: dict[str, Any], path: list[str]) -> Any:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _parse_iso(self, value: str | None) -> datetime | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            _log.warning(
                "coinbase_field_invalid_datetime",
                exchange=self._exchange,
                product_id=self._product_id,
                field="funding_time",
                value=value,
            )
            return None

    def _next_settlement_utc(self) -> datetime:
        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        noon = now.replace(hour=12, minute=0, second=0, microsecond=0)

        if now < noon:
            return noon

        if now < midnight + timedelta(days=1):
            return midnight + timedelta(days=1)

        return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
