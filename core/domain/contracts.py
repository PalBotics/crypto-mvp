from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.domain.normalize import ensure_utc, normalize_symbol, to_decimal


@dataclass(frozen=True, slots=True)
class MarketEvent:
    exchange: str
    adapter_name: str
    symbol: str
    bid_price: Decimal
    ask_price: Decimal
    mid_price: Decimal
    event_ts: datetime
    ingested_ts: datetime
    exchange_symbol: str = ""
    last_price: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    sequence_id: str | None = None

    def __post_init__(self) -> None:
        symbol, normalized_exchange_symbol = normalize_symbol(self.exchange, self.symbol)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "exchange_symbol",
            self.exchange_symbol.strip().upper() or normalized_exchange_symbol,
        )

        object.__setattr__(self, "bid_price", to_decimal(self.bid_price))
        object.__setattr__(self, "ask_price", to_decimal(self.ask_price))
        object.__setattr__(self, "mid_price", to_decimal(self.mid_price))
        object.__setattr__(
            self,
            "last_price",
            to_decimal(self.last_price) if self.last_price is not None else None,
        )
        object.__setattr__(
            self,
            "bid_size",
            to_decimal(self.bid_size) if self.bid_size is not None else None,
        )
        object.__setattr__(
            self,
            "ask_size",
            to_decimal(self.ask_size) if self.ask_size is not None else None,
        )

        object.__setattr__(self, "event_ts", ensure_utc(self.event_ts))
        object.__setattr__(self, "ingested_ts", ensure_utc(self.ingested_ts))


@dataclass(frozen=True, slots=True)
class FundingEvent:
    exchange: str
    adapter_name: str
    symbol: str
    funding_rate: Decimal
    event_ts: datetime
    ingested_ts: datetime
    exchange_symbol: str = ""
    funding_interval_hours: int | None = None
    predicted_funding_rate: Decimal | None = None
    mark_price: Decimal | None = None
    index_price: Decimal | None = None
    next_funding_ts: datetime | None = None

    def __post_init__(self) -> None:
        symbol, normalized_exchange_symbol = normalize_symbol(self.exchange, self.symbol)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "exchange_symbol",
            self.exchange_symbol.strip().upper() or normalized_exchange_symbol,
        )

        object.__setattr__(self, "funding_rate", to_decimal(self.funding_rate))
        object.__setattr__(
            self,
            "predicted_funding_rate",
            (
                to_decimal(self.predicted_funding_rate)
                if self.predicted_funding_rate is not None
                else None
            ),
        )
        object.__setattr__(
            self,
            "mark_price",
            to_decimal(self.mark_price) if self.mark_price is not None else None,
        )
        object.__setattr__(
            self,
            "index_price",
            to_decimal(self.index_price) if self.index_price is not None else None,
        )

        object.__setattr__(self, "event_ts", ensure_utc(self.event_ts))
        object.__setattr__(self, "ingested_ts", ensure_utc(self.ingested_ts))
        object.__setattr__(
            self,
            "next_funding_ts",
            ensure_utc(self.next_funding_ts) if self.next_funding_ts is not None else None,
        )


@dataclass(frozen=True, slots=True)
class OrderIntentContract:
    mode: str
    exchange: str
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    status: str
    created_ts: datetime
    exchange_symbol: str = ""
    strategy_signal_id: str | None = None
    portfolio_id: str | None = None
    time_in_force: str | None = None
    limit_price: Decimal | None = None
    reduce_only: bool = False
    post_only: bool = False
    client_order_id: str | None = None

    def __post_init__(self) -> None:
        symbol, normalized_exchange_symbol = normalize_symbol(self.exchange, self.symbol)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "exchange_symbol",
            self.exchange_symbol.strip().upper() or normalized_exchange_symbol,
        )

        object.__setattr__(self, "quantity", to_decimal(self.quantity))
        object.__setattr__(
            self,
            "limit_price",
            to_decimal(self.limit_price) if self.limit_price is not None else None,
        )
        object.__setattr__(self, "created_ts", ensure_utc(self.created_ts))


@dataclass(frozen=True, slots=True)
class FillEvent:
    exchange: str
    symbol: str
    side: str
    fill_price: Decimal
    fill_qty: Decimal
    fill_notional: Decimal
    fee_paid: Decimal
    fill_ts: datetime
    ingested_ts: datetime
    exchange_symbol: str = ""
    order_record_id: str | None = None
    order_intent_id: str | None = None
    exchange_trade_id: str | None = None
    liquidity_role: str | None = None
    fee_asset: str | None = None

    def __post_init__(self) -> None:
        symbol, normalized_exchange_symbol = normalize_symbol(self.exchange, self.symbol)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "exchange_symbol",
            self.exchange_symbol.strip().upper() or normalized_exchange_symbol,
        )

        object.__setattr__(self, "fill_price", to_decimal(self.fill_price))
        object.__setattr__(self, "fill_qty", to_decimal(self.fill_qty))
        object.__setattr__(self, "fill_notional", to_decimal(self.fill_notional))
        object.__setattr__(self, "fee_paid", to_decimal(self.fee_paid))

        object.__setattr__(self, "fill_ts", ensure_utc(self.fill_ts))
        object.__setattr__(self, "ingested_ts", ensure_utc(self.ingested_ts))
