"""Pydantic v2 response schemas for the dashboard API.

All Decimal fields are serialized as strings to avoid float precision loss.
Conversion from Decimal happens in the schema constructors; routes receive
plain dataclasses from core/reporting/queries.py and pass them here.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PositionSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    exchange: str
    symbol: str
    account_name: str
    quantity: str
    avg_entry_price: str
    snapshot_ts: datetime

    @classmethod
    def from_row(cls, row: object) -> "PositionSchema":
        return cls(
            exchange=row.exchange,  # type: ignore[attr-defined]
            symbol=row.symbol,  # type: ignore[attr-defined]
            account_name=row.account_name,  # type: ignore[attr-defined]
            quantity=str(row.quantity),  # type: ignore[attr-defined]
            avg_entry_price=str(row.avg_entry_price),  # type: ignore[attr-defined]
            snapshot_ts=row.snapshot_ts,  # type: ignore[attr-defined]
        )


class PnLSummarySchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_realized_pnl: str
    total_unrealized_pnl: str
    total_funding_paid: str
    net_pnl: str

    @classmethod
    def from_row(cls, row: object) -> "PnLSummarySchema":
        return cls(
            total_realized_pnl=str(row.total_realized_pnl),  # type: ignore[attr-defined]
            total_unrealized_pnl=str(row.total_unrealized_pnl),  # type: ignore[attr-defined]
            total_funding_paid=str(row.total_funding_paid),  # type: ignore[attr-defined]
            net_pnl=str(row.net_pnl),  # type: ignore[attr-defined]
        )


class FillSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    fill_ts: datetime
    exchange: str
    symbol: str
    side: str
    fill_price: str
    fill_qty: str
    fee_amount: str

    @classmethod
    def from_row(cls, row: object) -> "FillSchema":
        return cls(
            fill_ts=row.fill_ts,  # type: ignore[attr-defined]
            exchange=row.exchange,  # type: ignore[attr-defined]
            symbol=row.symbol,  # type: ignore[attr-defined]
            side=row.side,  # type: ignore[attr-defined]
            fill_price=str(row.fill_price),  # type: ignore[attr-defined]
            fill_qty=str(row.fill_qty),  # type: ignore[attr-defined]
            fee_amount=str(row.fee_amount),  # type: ignore[attr-defined]
        )


class RiskEventSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created_ts: datetime
    rule_name: str
    event_type: str
    severity: str
    details: dict

    @classmethod
    def from_row(cls, row: object) -> "RiskEventSchema":
        return cls(
            created_ts=row.created_ts,  # type: ignore[attr-defined]
            rule_name=row.rule_name,  # type: ignore[attr-defined]
            event_type=row.event_type,  # type: ignore[attr-defined]
            severity=row.severity,  # type: ignore[attr-defined]
            details=row.details,  # type: ignore[attr-defined]
        )


class RunSummarySchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_name: str
    open_position_count: int
    total_fills: int
    total_risk_events: int
    realized_pnl: str
    unrealized_pnl: str
    funding_paid: str
    net_pnl: str

    @classmethod
    def from_row(cls, row: object) -> "RunSummarySchema":
        return cls(
            account_name=row.account_name,  # type: ignore[attr-defined]
            open_position_count=row.open_position_count,  # type: ignore[attr-defined]
            total_fills=row.total_fills,  # type: ignore[attr-defined]
            total_risk_events=row.total_risk_events,  # type: ignore[attr-defined]
            realized_pnl=str(row.realized_pnl),  # type: ignore[attr-defined]
            unrealized_pnl=str(row.unrealized_pnl),  # type: ignore[attr-defined]
            funding_paid=str(row.funding_paid),  # type: ignore[attr-defined]
            net_pnl=str(row.net_pnl),  # type: ignore[attr-defined]
        )


class MarketTickSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    exchange: str
    symbol: str
    bid_price: str
    ask_price: str
    mid_price: str
    last_price: str | None
    event_ts: datetime

    @classmethod
    def from_row(cls, row: object) -> "MarketTickSchema":
        return cls(
            exchange=row.exchange,  # type: ignore[attr-defined]
            symbol=row.symbol,  # type: ignore[attr-defined]
            bid_price=str(row.bid_price),  # type: ignore[attr-defined]
            ask_price=str(row.ask_price),  # type: ignore[attr-defined]
            mid_price=str(row.mid_price),  # type: ignore[attr-defined]
            last_price=None if row.last_price is None else str(row.last_price),  # type: ignore[attr-defined]
            event_ts=row.event_ts,  # type: ignore[attr-defined]
        )


class OrderBookSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    exchange: str
    symbol: str
    bid_price_1: str
    bid_size_1: str
    ask_price_1: str
    ask_size_1: str
    spread: str | None
    spread_bps: str | None
    mid_price: str | None
    event_ts: datetime

    @classmethod
    def from_row(cls, row: object) -> "OrderBookSchema":
        return cls(
            exchange=row.exchange,  # type: ignore[attr-defined]
            symbol=row.symbol,  # type: ignore[attr-defined]
            bid_price_1=str(row.bid_price_1),  # type: ignore[attr-defined]
            bid_size_1=str(row.bid_size_1),  # type: ignore[attr-defined]
            ask_price_1=str(row.ask_price_1),  # type: ignore[attr-defined]
            ask_size_1=str(row.ask_size_1),  # type: ignore[attr-defined]
            spread=None if row.spread is None else str(row.spread),  # type: ignore[attr-defined]
            spread_bps=None if row.spread_bps is None else str(row.spread_bps),  # type: ignore[attr-defined]
            mid_price=None if row.mid_price is None else str(row.mid_price),  # type: ignore[attr-defined]
            event_ts=row.event_ts,  # type: ignore[attr-defined]
        )


class FundingRateSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    exchange: str
    symbol: str
    funding_rate: str
    predicted_funding_rate: str | None
    mark_price: str | None
    next_funding_ts: datetime | None
    event_ts: datetime

    @classmethod
    def from_row(cls, row: object) -> "FundingRateSchema":
        return cls(
            exchange=row.exchange,  # type: ignore[attr-defined]
            symbol=row.symbol,  # type: ignore[attr-defined]
            funding_rate=str(row.funding_rate),  # type: ignore[attr-defined]
            predicted_funding_rate=None
            if row.predicted_funding_rate is None
            else str(row.predicted_funding_rate),  # type: ignore[attr-defined]
            mark_price=None if row.mark_price is None else str(row.mark_price),  # type: ignore[attr-defined]
            next_funding_ts=row.next_funding_ts,  # type: ignore[attr-defined]
            event_ts=row.event_ts,  # type: ignore[attr-defined]
        )
