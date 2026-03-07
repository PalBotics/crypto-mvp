from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from core.domain.contracts import FillEvent, MarketEvent, OrderIntentContract
from core.models.fill_record import FillRecord
from core.models.market_tick import MarketTick
from core.models.order_intent import OrderIntent
from core.paper.simulator import PaperExecutionResult


def order_intent_to_contract(order_intent: OrderIntent) -> OrderIntentContract:
    """Map OrderIntent ORM model to OrderIntentContract."""
    return OrderIntentContract(
        mode=order_intent.mode,
        exchange=order_intent.exchange,
        symbol=order_intent.symbol,
        side=order_intent.side,
        order_type=order_intent.order_type,
        quantity=order_intent.quantity,
        status=order_intent.status,
        created_ts=order_intent.created_ts,
        strategy_signal_id=(
            str(order_intent.strategy_signal_id)
            if order_intent.strategy_signal_id is not None
            else None
        ),
        portfolio_id=(
            str(order_intent.portfolio_id) if order_intent.portfolio_id is not None else None
        ),
        time_in_force=order_intent.time_in_force,
        limit_price=order_intent.limit_price,
        reduce_only=order_intent.reduce_only,
        post_only=order_intent.post_only,
        client_order_id=order_intent.client_order_id,
    )


def market_tick_to_event(tick: MarketTick) -> MarketEvent:
    """Map MarketTick ORM model to MarketEvent contract."""
    return MarketEvent(
        exchange=tick.exchange,
        adapter_name=tick.adapter_name,
        symbol=tick.symbol,
        exchange_symbol=tick.exchange_symbol,
        bid_price=tick.bid_price,
        ask_price=tick.ask_price,
        mid_price=tick.mid_price,
        last_price=tick.last_price,
        bid_size=tick.bid_size,
        ask_size=tick.ask_size,
        event_ts=tick.event_ts,
        ingested_ts=tick.ingested_ts,
        sequence_id=tick.sequence_id,
    )


def fill_event_to_record(fill: FillEvent) -> FillRecord:
    """Map FillEvent contract to FillRecord ORM instance."""
    order_record_id: UUID | None = None
    if fill.order_record_id:
        order_record_id = UUID(fill.order_record_id)

    return FillRecord(
        order_record_id=order_record_id,
        exchange=fill.exchange,
        symbol=fill.symbol,
        exchange_trade_id=fill.exchange_trade_id,
        side=fill.side,
        fill_price=fill.fill_price,
        fill_qty=fill.fill_qty,
        fill_notional=fill.fill_notional,
        liquidity_role=fill.liquidity_role,
        fee_paid=fill.fee_paid,
        fee_asset=fill.fee_asset,
        fill_ts=fill.fill_ts,
        ingested_ts=fill.ingested_ts,
    )


@dataclass(frozen=True, slots=True)
class OrderRecordFilledUpdate:
    """Minimal payload for creating/updating a filled OrderRecord in Sprint 4."""

    status: str
    submitted_qty: Decimal
    filled_qty: Decimal
    avg_fill_price: Decimal
    fees_paid: Decimal
    created_ts: datetime
    updated_ts: datetime
    fee_asset: str | None = None
    submitted_price: Decimal | None = None


def order_record_update_from_execution(
    execution: PaperExecutionResult,
) -> OrderRecordFilledUpdate:
    """Build minimal OrderRecord update values from paper execution result."""
    return OrderRecordFilledUpdate(
        status=execution.order_status,
        submitted_qty=execution.filled_quantity,
        filled_qty=execution.filled_quantity,
        avg_fill_price=execution.average_fill_price,
        fees_paid=execution.fee_paid,
        created_ts=execution.submitted_ts,
        updated_ts=execution.fill_ts,
        fee_asset=execution.fill_event.fee_asset,
        submitted_price=None,
    )
