from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick
from core.models.order_book_snapshot import OrderBookSnapshot


class CollectorError(RuntimeError):
    """Raised when collector HTTP/API responses are invalid."""


@dataclass(frozen=True)
class CollectorConfig:
    spot_exchange: str = "kraken"
    perp_exchange: str = "kraken_futures"
    spot_symbol: str = "XBTUSD"
    perp_symbol: str = "XBTUSD"
    spot_exchange_symbol: str = "XXBTZUSD"
    perp_exchange_symbol: str = "PF_XBTUSD"
    adapter_name: str = "kraken_rest"
    poll_interval_seconds: int = 60
    spot_base_url: str = "https://api.kraken.com"
    futures_base_url: str = "https://futures.kraken.com"
    request_timeout_seconds: int = 10


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _parse_iso_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class KrakenRestAdapter:
    """REST polling adapter for Kraken spot and Kraken futures public endpoints."""

    def __init__(self, config: CollectorConfig) -> None:
        self._config = config

    def fetch_spot_ticker(self) -> dict:
        url = f"{self._config.spot_base_url}/0/public/Ticker"
        response = httpx.get(
            url,
            params={"pair": self._config.spot_symbol},
            timeout=self._config.request_timeout_seconds,
        )
        if response.status_code != 200:
            raise CollectorError(f"Kraken spot HTTP status {response.status_code}")

        payload = response.json()
        errors = payload.get("error", [])
        if errors:
            raise CollectorError(f"Kraken spot API error: {errors}")
        if "result" not in payload:
            raise CollectorError("Kraken spot API payload missing 'result'")
        return payload

    def fetch_futures_tickers(self) -> list[dict]:
        url = f"{self._config.futures_base_url}/derivatives/api/v3/tickers"
        response = httpx.get(
            url,
            timeout=self._config.request_timeout_seconds,
        )
        if response.status_code != 200:
            raise CollectorError(f"Kraken futures HTTP status {response.status_code}")

        payload = response.json()
        errors = payload.get("error", [])
        if errors:
            raise CollectorError(f"Kraken futures API error: {errors}")

        tickers = payload.get("tickers")
        if not isinstance(tickers, list):
            raise CollectorError("Kraken futures API payload missing 'tickers' list")
        return tickers

    def fetch_order_book(self) -> dict:
        url = f"{self._config.spot_base_url}/0/public/Depth"
        response = httpx.get(
            url,
            params={"pair": self._config.spot_symbol, "count": 3},
            timeout=self._config.request_timeout_seconds,
        )
        if response.status_code != 200:
            raise CollectorError(f"Kraken order book HTTP status {response.status_code}")

        payload = response.json()
        errors = payload.get("error", [])
        if errors:
            raise CollectorError(f"Kraken order book API error: {errors}")
        if "result" not in payload:
            raise CollectorError("Kraken order book API payload missing 'result'")
        return payload

    def parse_order_book_snapshot(self, raw: dict) -> OrderBookSnapshot:
        result = raw["result"]
        book = result[self._config.spot_exchange_symbol]
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if len(bids) == 0 or len(asks) == 0:
            raise CollectorError("Kraken order book payload missing top-of-book bids/asks")

        def _level(levels: list, idx: int) -> tuple[Decimal | None, Decimal | None]:
            if idx >= len(levels):
                return None, None
            row = levels[idx]
            if not isinstance(row, list) or len(row) < 2:
                return None, None
            return _to_decimal(row[0]), _to_decimal(row[1])

        bid_price_1, bid_size_1 = _level(bids, 0)
        ask_price_1, ask_size_1 = _level(asks, 0)
        if bid_price_1 is None or bid_size_1 is None or ask_price_1 is None or ask_size_1 is None:
            raise CollectorError("Kraken order book payload missing valid level-1 bids/asks")

        bid_price_2, bid_size_2 = _level(bids, 1)
        ask_price_2, ask_size_2 = _level(asks, 1)
        bid_price_3, bid_size_3 = _level(bids, 2)
        ask_price_3, ask_size_3 = _level(asks, 2)

        spread = ask_price_1 - bid_price_1
        mid_price = (bid_price_1 + ask_price_1) / Decimal("2")
        spread_bps = (spread / mid_price * Decimal("10000")) if mid_price != 0 else None
        now_utc = datetime.now(timezone.utc)

        return OrderBookSnapshot(
            exchange=self._config.spot_exchange,
            adapter_name=self._config.adapter_name,
            symbol=self._config.spot_symbol,
            exchange_symbol=self._config.spot_exchange_symbol,
            bid_price_1=bid_price_1,
            bid_size_1=bid_size_1,
            ask_price_1=ask_price_1,
            ask_size_1=ask_size_1,
            bid_price_2=bid_price_2,
            bid_size_2=bid_size_2,
            ask_price_2=ask_price_2,
            ask_size_2=ask_size_2,
            bid_price_3=bid_price_3,
            bid_size_3=bid_size_3,
            ask_price_3=ask_price_3,
            ask_size_3=ask_size_3,
            spread=spread,
            spread_bps=spread_bps,
            mid_price=mid_price,
            event_ts=now_utc,
            ingested_ts=now_utc,
        )

    def parse_spot_tick(self, raw: dict) -> MarketTick:
        result = raw.get("result", {})
        spot_data = result.get(self._config.spot_exchange_symbol)
        if spot_data is None and result:
            # Fallback to first result entry if exchange symbol key differs.
            spot_data = next(iter(result.values()))
        if spot_data is None:
            raise CollectorError("Kraken spot ticker payload missing symbol entry")

        bid = _to_decimal((spot_data.get("b") or [None])[0])
        ask = _to_decimal((spot_data.get("a") or [None])[0])
        last = _to_decimal((spot_data.get("c") or [None])[0])
        now_utc = datetime.now(timezone.utc)

        return MarketTick(
            exchange=self._config.spot_exchange,
            adapter_name=self._config.adapter_name,
            symbol=self._config.spot_symbol,
            exchange_symbol=self._config.spot_exchange_symbol,
            bid_price=bid,
            ask_price=ask,
            mid_price=(bid + ask) / Decimal("2"),
            last_price=last,
            bid_size=None,
            ask_size=None,
            event_ts=now_utc,
            ingested_ts=now_utc,
            sequence_id=None,
        )

    def parse_perp_tick(self, raw: dict) -> MarketTick:
        bid = _to_decimal(raw.get("bid"))
        ask = _to_decimal(raw.get("ask"))
        last = _to_decimal(raw.get("last"))
        now_utc = datetime.now(timezone.utc)

        return MarketTick(
            exchange=self._config.perp_exchange,
            adapter_name=self._config.adapter_name,
            symbol=self._config.perp_symbol,
            exchange_symbol=self._config.perp_exchange_symbol,
            bid_price=bid,
            ask_price=ask,
            mid_price=(bid + ask) / Decimal("2"),
            last_price=last,
            bid_size=None,
            ask_size=None,
            event_ts=now_utc,
            ingested_ts=now_utc,
            sequence_id=None,
        )

    def parse_funding_snapshot(self, raw: dict) -> FundingRateSnapshot:
        now_utc = datetime.now(timezone.utc)
        return FundingRateSnapshot(
            exchange=self._config.perp_exchange,
            adapter_name=self._config.adapter_name,
            symbol=self._config.perp_symbol,
            exchange_symbol=self._config.perp_exchange_symbol,
            funding_rate=_to_decimal(raw.get("fundingRate")),
            funding_interval_hours=4,
            predicted_funding_rate=(
                _to_decimal(raw.get("fundingRateRelative"))
                if raw.get("fundingRateRelative") is not None
                else None
            ),
            mark_price=(
                _to_decimal(raw.get("markPrice"))
                if raw.get("markPrice") is not None
                else None
            ),
            index_price=(
                _to_decimal(raw.get("indexPrice"))
                if raw.get("indexPrice") is not None
                else None
            ),
            next_funding_ts=_parse_iso_utc(raw.get("next_funding_rate_time")),
            event_ts=now_utc,
            ingested_ts=now_utc,
        )
