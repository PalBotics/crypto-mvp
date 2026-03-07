from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.fill_record import FillRecord
from core.models.funding_payment import FundingPayment
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


@dataclass(frozen=True)
class KPIResult:
    annualized_return: Decimal
    max_drawdown: Decimal
    fee_drag: Decimal
    funding_income_captured: Decimal
    missed_opportunity_count: int


def calculate_kpis(
    session: Session,
    account_name: str,
    start_ts: datetime,
    end_ts: datetime,
    entry_threshold: Decimal,
    initial_capital: Decimal,
) -> KPIResult:
    realized_total = _to_decimal(
        session.execute(
            select(func.sum(PnLSnapshot.realized_pnl))
            .where(PnLSnapshot.strategy_name == account_name)
            .where(PnLSnapshot.snapshot_ts >= start_ts)
            .where(PnLSnapshot.snapshot_ts <= end_ts)
        ).scalar_one()
    )
    funding_total = _to_decimal(
        session.execute(
            select(func.sum(FundingPayment.payment_amount))
            .where(FundingPayment.account_name == account_name)
            .where(FundingPayment.accrued_ts >= start_ts)
            .where(FundingPayment.accrued_ts <= end_ts)
        ).scalar_one()
    )

    elapsed_seconds = Decimal(str(max((end_ts - start_ts).total_seconds(), 0.0)))
    annualized_return = Decimal("0")
    if elapsed_seconds > Decimal("0") and initial_capital != Decimal("0"):
        period_return = (realized_total + funding_total) / initial_capital
        elapsed_years = elapsed_seconds / Decimal(str(365.25 * 24 * 3600))
        base_return = Decimal("1") + period_return
        if elapsed_years > Decimal("0") and base_return > Decimal("0"):
            # Decimal is used throughout; float is used only for exponentiation,
            # then converted back to Decimal immediately.
            try:
                annualized_float = float(base_return) ** (1.0 / float(elapsed_years)) - 1.0
                annualized_return = Decimal(str(annualized_float))
            except OverflowError:
                annualized_return = Decimal("0")

    pnl_rows = session.execute(
        select(PnLSnapshot.snapshot_ts, PnLSnapshot.realized_pnl)
        .where(PnLSnapshot.strategy_name == account_name)
        .where(PnLSnapshot.snapshot_ts >= start_ts)
        .where(PnLSnapshot.snapshot_ts <= end_ts)
        .order_by(PnLSnapshot.snapshot_ts.asc())
    ).all()

    max_drawdown = Decimal("0")
    if len(pnl_rows) >= 2:
        funding_rows = session.execute(
            select(FundingPayment.accrued_ts, FundingPayment.payment_amount)
            .where(FundingPayment.account_name == account_name)
            .where(FundingPayment.accrued_ts >= start_ts)
            .where(FundingPayment.accrued_ts <= end_ts)
            .order_by(FundingPayment.accrued_ts.asc())
        ).all()

        funding_idx = 0
        cumulative_realized = Decimal("0")
        cumulative_funding = Decimal("0")
        peak = Decimal("0")

        for snapshot_ts, realized_pnl in pnl_rows:
            cumulative_realized += _to_decimal(realized_pnl)
            while funding_idx < len(funding_rows) and funding_rows[funding_idx][0] <= snapshot_ts:
                cumulative_funding += _to_decimal(funding_rows[funding_idx][1])
                funding_idx += 1

            cumulative_pnl = cumulative_realized + cumulative_funding
            if cumulative_pnl > peak:
                peak = cumulative_pnl
            drawdown = peak - cumulative_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown

    total_fees = _to_decimal(
        session.execute(
            select(func.sum(FillRecord.fee_paid))
            .select_from(FillRecord)
            .join(OrderRecord, OrderRecord.id == FillRecord.order_record_id)
            .join(OrderIntent, OrderIntent.id == OrderRecord.order_intent_id)
            .where(OrderIntent.mode == account_name)
            .where(FillRecord.fill_ts >= start_ts)
            .where(FillRecord.fill_ts <= end_ts)
        ).scalar_one()
    )

    gross_funding_income = _to_decimal(
        session.execute(
            select(func.sum(FundingPayment.payment_amount))
            .where(FundingPayment.account_name == account_name)
            .where(FundingPayment.accrued_ts >= start_ts)
            .where(FundingPayment.accrued_ts <= end_ts)
            .where(FundingPayment.payment_amount > Decimal("0"))
        ).scalar_one()
    )
    fee_drag = Decimal("0")
    if gross_funding_income != Decimal("0"):
        fee_drag = total_fees / gross_funding_income

    high_rate_snapshots = session.execute(
        select(FundingRateSnapshot.event_ts)
        .where(FundingRateSnapshot.event_ts >= start_ts)
        .where(FundingRateSnapshot.event_ts <= end_ts)
        .where(FundingRateSnapshot.funding_rate >= entry_threshold)
        .order_by(FundingRateSnapshot.event_ts.asc())
    ).all()

    position_rows = session.execute(
        select(PositionSnapshot.snapshot_ts, PositionSnapshot.symbol, PositionSnapshot.quantity)
        .where(PositionSnapshot.account_name == account_name)
        .where(PositionSnapshot.snapshot_ts <= end_ts)
        .order_by(PositionSnapshot.snapshot_ts.asc())
    ).all()

    missed_opportunity_count = 0
    position_idx = 0
    latest_qty_by_symbol: dict[str, Decimal] = {}
    for (snapshot_ts,) in high_rate_snapshots:
        while position_idx < len(position_rows) and position_rows[position_idx][0] <= snapshot_ts:
            _, symbol, qty = position_rows[position_idx]
            latest_qty_by_symbol[symbol] = _to_decimal(qty)
            position_idx += 1
        open_exists = any(qty > Decimal("0") for qty in latest_qty_by_symbol.values())
        if not open_exists:
            missed_opportunity_count += 1

    return KPIResult(
        annualized_return=annualized_return,
        max_drawdown=max_drawdown,
        fee_drag=fee_drag,
        funding_income_captured=funding_total,
        missed_opportunity_count=missed_opportunity_count,
    )