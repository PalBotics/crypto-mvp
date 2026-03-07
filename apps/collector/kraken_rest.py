from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick


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
