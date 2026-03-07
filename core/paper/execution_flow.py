from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.market_tick import MarketTick
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


def execute_one_paper_market_intent(
    session: Session,
    fee_model: FeeModel,
    risk_engine: RiskEngine | None = None,
    funding_rate: Decimal = Decimal("0"),
    latest_funding_ts: datetime | None = None,
) -> bool:
    """Execute at most one eligible paper market order intent.

    Returns:
        True if one intent was executed and persisted, otherwise False.
    """
    intent = (
        session.execute(
            select(OrderIntent)
            .where(OrderIntent.mode == "paper")
            .where(OrderIntent.order_type == "market")
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
    execution = simulator.simulate(
        order_intent_to_contract(intent),
        market_tick_to_event(tick),
    )

    order_record = order_record_from_intent_execution(intent, execution)
    session.add(order_record)

    fill_event = replace(
        execution.fill_event,
        order_intent_id=str(intent.id) if intent.id is not None else None,
        order_record_id=str(order_record.id),
    )
    fill_record = fill_event_to_record(fill_event)
    session.add(fill_record)
    position_snapshot = update_position_from_fill(session, fill_record, mode="paper")
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
