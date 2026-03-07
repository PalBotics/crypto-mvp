from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.paper_trader.main import IterationSummary, PaperTradingLoop
from core.models.fill_record import FillRecord
from core.models.funding_payment import FundingPayment
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.paper.fees import FixedBpsFeeModel
from core.risk.engine import RiskConfig, RiskEngine
from core.strategy.funding_capture import FundingCaptureConfig, FundingCaptureStrategy


@dataclass(frozen=True)
class ReplayConfig:
    exchange: str
    spot_symbol: str
    perp_symbol: str
    start_ts: datetime
    end_ts: datetime
    entry_funding_rate_threshold: Decimal
    exit_funding_rate_threshold: Decimal
    position_size: Decimal
    max_data_age_seconds: int
    max_notional_per_symbol: Decimal
    min_entry_funding_rate: Decimal
    fee_bps: Decimal


@dataclass(frozen=True)
class ReplaySummary:
    run_id: str
    exchange: str
    symbol: str
    snapshots_replayed: int
    iterations_with_entry: int
    iterations_with_exit: int
    total_fills: int
    total_funding_payments: int
    final_position_quantity: Decimal
    total_realized_pnl: Decimal
    total_funding_paid: Decimal
    start_ts: datetime
    end_ts: datetime


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _count_iterations_by_reduce_only(session: Session, run_id: str, reduce_only: bool) -> int:
    stmt = select(func.count(OrderIntent.id)).where(OrderIntent.mode == run_id).where(
        OrderIntent.reduce_only == reduce_only
    )
    intent_count = int(session.execute(stmt).scalar_one())
    # FundingCaptureStrategy emits two intents per entry/exit iteration (spot+perp).
    return intent_count // 2


def _count_fills_for_run(session: Session, run_id: str) -> int:
    stmt = (
        select(func.count(FillRecord.id))
        .select_from(FillRecord)
        .join(OrderRecord, OrderRecord.id == FillRecord.order_record_id)
        .join(OrderIntent, OrderIntent.id == OrderRecord.order_intent_id)
        .where(OrderIntent.mode == run_id)
    )
    return int(session.execute(stmt).scalar_one())


def run_replay(session: Session, config: ReplayConfig) -> ReplaySummary:
    run_id = str(uuid4())

    snapshots = (
        session.execute(
            select(FundingRateSnapshot)
            .where(FundingRateSnapshot.exchange == config.exchange)
            .where(FundingRateSnapshot.symbol == config.perp_symbol)
            .where(FundingRateSnapshot.event_ts >= config.start_ts)
            .where(FundingRateSnapshot.event_ts <= config.end_ts)
            .order_by(FundingRateSnapshot.event_ts.asc())
        )
        .scalars()
        .all()
    )

    if not snapshots:
        return ReplaySummary(
            run_id=run_id,
            exchange=config.exchange,
            symbol=config.perp_symbol,
            snapshots_replayed=0,
            iterations_with_entry=0,
            iterations_with_exit=0,
            total_fills=0,
            total_funding_payments=0,
            final_position_quantity=Decimal("0"),
            total_realized_pnl=Decimal("0"),
            total_funding_paid=Decimal("0"),
            start_ts=config.start_ts,
            end_ts=config.end_ts,
        )

    market_data = [
        (
            _to_decimal(snapshot.funding_rate),
            _to_decimal(snapshot.mark_price),
        )
        for snapshot in snapshots
    ]

    strategy_config = FundingCaptureConfig(
        spot_symbol=config.spot_symbol,
        perp_symbol=config.perp_symbol,
        exchange=config.exchange,
        entry_funding_rate_threshold=config.entry_funding_rate_threshold,
        exit_funding_rate_threshold=config.exit_funding_rate_threshold,
        position_size=config.position_size,
        mode=run_id,
    )
    risk_config = RiskConfig(
        max_data_age_seconds=config.max_data_age_seconds,
        min_entry_funding_rate=config.min_entry_funding_rate,
        max_notional_per_symbol=config.max_notional_per_symbol,
    )

    loop = PaperTradingLoop(
        session=session,
        strategy=FundingCaptureStrategy(strategy_config),
        risk_engine=RiskEngine(risk_config),
        fee_model=FixedBpsFeeModel(bps=config.fee_bps),
        iterations=len(market_data),
        market_data=market_data,
    )

    loop.run()

    iterations_with_entry = _count_iterations_by_reduce_only(
        session, run_id, reduce_only=False
    )
    iterations_with_exit = _count_iterations_by_reduce_only(
        session, run_id, reduce_only=True
    )

    total_fills = _count_fills_for_run(session, run_id)

    total_funding_payments = int(
        session.execute(
            select(func.count(FundingPayment.id)).where(FundingPayment.account_name == run_id)
        ).scalar_one()
    )

    latest_perp_position = (
        session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.exchange == config.exchange)
            .where(PositionSnapshot.symbol == config.perp_symbol)
            .where(PositionSnapshot.account_name == run_id)
            .order_by(PositionSnapshot.snapshot_ts.desc())
        )
        .scalars()
        .first()
    )
    final_position_quantity = (
        _to_decimal(latest_perp_position.quantity)
        if latest_perp_position is not None
        else Decimal("0")
    )

    total_realized_pnl = _to_decimal(
        session.execute(
            select(func.sum(PnLSnapshot.realized_pnl)).where(PnLSnapshot.strategy_name == run_id)
        ).scalar_one()
    )

    total_funding_paid = _to_decimal(
        session.execute(
            select(func.sum(FundingPayment.payment_amount)).where(FundingPayment.account_name == run_id)
        ).scalar_one()
    )

    return ReplaySummary(
        run_id=run_id,
        exchange=config.exchange,
        symbol=config.perp_symbol,
        snapshots_replayed=len(snapshots),
        iterations_with_entry=iterations_with_entry,
        iterations_with_exit=iterations_with_exit,
        total_fills=total_fills,
        total_funding_payments=total_funding_payments,
        final_position_quantity=final_position_quantity,
        total_realized_pnl=total_realized_pnl,
        total_funding_paid=total_funding_paid,
        start_ts=snapshots[0].event_ts,
        end_ts=snapshots[-1].event_ts,
    )
