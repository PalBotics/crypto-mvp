from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.market_tick import MarketTick
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.order_intent import OrderIntent
from core.paper.contracts_adapters import (
    fill_event_to_record,
    market_tick_to_event,
    order_intent_to_contract,
    order_record_from_intent_execution,
)
from core.paper.fees import FeeModel
from core.paper.pnl_calculator import create_pnl_snapshot_from_fill
from core.paper.position_tracker import update_position_from_fill
from core.paper.simulator import PaperOrderSimulator
from core.risk.engine import RiskEngine
from core.utils.logging import get_logger

_log = get_logger(__name__)


def execute_one_paper_market_intent(
    session: Session,
    fee_model: FeeModel,
    risk_engine: RiskEngine | None = None,
    funding_rate: Decimal = Decimal("0"),
    latest_funding_ts: datetime | None = None,
    mode: str = "paper",
    order_book_snapshot: OrderBookSnapshot | None = None,
) -> bool:
    """Execute at most one eligible paper market order intent.

    Returns:
        True if one intent was executed and persisted, otherwise False.
    """
    intent = (
        session.execute(
            select(OrderIntent)
            .where(OrderIntent.mode == mode)
            .where(OrderIntent.status == "pending")
            .order_by(OrderIntent.created_ts.asc())
        )
        .scalars()
        .first()
    )

    if intent is None:
        return False

    tick = (
        session.execute(
            select(MarketTick)
            .where(MarketTick.exchange == intent.exchange)
            .where(MarketTick.symbol == intent.symbol)
            .order_by(MarketTick.event_ts.desc())
        )
        .scalars()
        .first()
    )

    if tick is None:
        return False

    if risk_engine is not None:
        _funding_ts = latest_funding_ts if latest_funding_ts is not None else datetime.now(timezone.utc)
        result = risk_engine.check(
            session=session,
            order_intent=intent,
            funding_rate=funding_rate,
            mark_price=Decimal(str(tick.ask_price)),
            latest_funding_ts=_funding_ts,
        )
        if not result.passed:
            intent.status = "rejected"
            # Keep transaction ownership with caller while making status visible
            # to subsequent pending-intent queries in autoflush-disabled loops.
            session.flush()
            return False

    simulator = PaperOrderSimulator(fee_model=fee_model)
    intent_contract = order_intent_to_contract(intent)
    if intent_contract.mode.strip().lower() != "paper":
        # Replay runs use mode as a run identifier; simulator still expects paper mode.
        intent_contract = replace(intent_contract, mode="paper")

    market_event = market_tick_to_event(tick)
    order_type = intent_contract.order_type.strip().lower()
    if order_type == "limit":
        snapshot = order_book_snapshot
        if snapshot is None:
            _log.info("limit_order_no_snapshot")
            return False

        side = intent_contract.side.strip().lower()
        limit_price = intent_contract.limit_price
        if snapshot is None or limit_price is None:
            _log.info(
                "limit_order_not_filled",
                side=side,
                limit_price=(str(limit_price) if limit_price is not None else None),
                market_price=None,
            )
            return False

        market_price = (
            Decimal(str(snapshot.ask_price_1)) if side == "buy" else Decimal(str(snapshot.bid_price_1))
        )
        is_fillable = (
            market_price <= limit_price if side == "buy" else market_price >= limit_price
        )
        if not is_fillable:
            _log.info(
                "limit_order_not_filled",
                side=side,
                limit_price=str(limit_price),
                market_price=str(market_price),
            )
            return False

        # Maker assumption: fill at limit price when touched/crossed.
        if side == "buy":
            market_event = replace(market_event, ask_price=limit_price, mid_price=limit_price)
        else:
            market_event = replace(market_event, bid_price=limit_price, mid_price=limit_price)
        intent_contract = replace(intent_contract, order_type="market")
    elif order_type != "market":
        raise ValueError(f"Unsupported order_type for paper execution: {intent_contract.order_type}")

    execution = simulator.simulate(
        intent_contract,
        market_event,
    )

    order_record = order_record_from_intent_execution(intent, execution)
    session.add(order_record)
    # Ensure the parent order_record row is visible before inserting fill_record.
    session.flush()

    fill_event = replace(
        execution.fill_event,
        order_intent_id=str(intent.id) if intent.id is not None else None,
        order_record_id=str(order_record.id),
    )
    fill_record = fill_event_to_record(fill_event)
    session.add(fill_record)
    position_snapshot = update_position_from_fill(session, fill_record, mode=mode)
    create_pnl_snapshot_from_fill(
        session=session,
        fill_record=fill_record,
        position_snapshot=position_snapshot,
        mark_price=fill_record.fill_price,
    )

    intent.status = "filled"
    # Persist all pending writes without committing; caller decides commit/rollback.
    session.flush()
    return True
