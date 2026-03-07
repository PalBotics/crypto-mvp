from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.domain.contracts import FillEvent, MarketEvent, OrderIntentContract
from core.domain.normalize import to_decimal
from core.paper.fees import FeeModel


@dataclass(frozen=True, slots=True)
class PaperExecutionResult:
    """Minimal result payload from paper order simulation."""

    order_status: str
    filled_quantity: Decimal
    average_fill_price: Decimal
    fee_paid: Decimal
    submitted_ts: datetime
    fill_ts: datetime
    fill_event: FillEvent


@dataclass(frozen=True, slots=True)
class PaperOrderSimulator:
    """Minimal paper order simulator for Sprint 4 MVP."""

    fee_model: FeeModel

    def simulate(
        self,
        intent: OrderIntentContract,
        market: MarketEvent,
    ) -> PaperExecutionResult:
        mode = intent.mode.strip().lower()
        if mode != "paper":
            raise ValueError(f"Unsupported mode for paper simulator: {intent.mode}")

        order_type = intent.order_type.strip().lower()
        if order_type != "market":
            raise ValueError(
                f"Unsupported order_type for paper simulator: {intent.order_type}"
            )

        side = intent.side.strip().lower()
        if side == "buy":
            fill_price = market.ask_price
        elif side == "sell":
            fill_price = market.bid_price
        else:
            raise ValueError(f"Unsupported side for paper simulator: {intent.side}")

        fill_qty = to_decimal(intent.quantity)
        fill_notional = fill_price * fill_qty
        fee_paid = self.fee_model.calculate_fee(fill_notional)

        fill_event = FillEvent(
            exchange=intent.exchange,
            symbol=intent.symbol,
            exchange_symbol=intent.exchange_symbol,
            side=intent.side,
            fill_price=fill_price,
            fill_qty=fill_qty,
            fill_notional=fill_notional,
            fee_paid=fee_paid,
            fill_ts=market.event_ts,
            ingested_ts=market.ingested_ts,
            liquidity_role="taker",
            order_intent_id=None,
        )

        return PaperExecutionResult(
            order_status="filled",
            filled_quantity=fill_qty,
            average_fill_price=fill_price,
            fee_paid=fee_paid,
            submitted_ts=intent.created_ts,
            fill_ts=fill_event.fill_ts,
            fill_event=fill_event,
        )
