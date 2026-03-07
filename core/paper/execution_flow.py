from __future__ import annotations

from dataclasses import replace

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
from core.paper.simulator import PaperOrderSimulator


def execute_one_paper_market_intent(session: Session, fee_model: FeeModel) -> bool:
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

    intent.status = "filled"
    session.commit()
    return True
