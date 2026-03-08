from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.fill_record import FillRecord
from core.models.funding_payment import FundingPayment
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.order_book_snapshot import OrderBookSnapshot
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


@dataclass(frozen=True)
class MMKPIResult:
    account_name: str
    start_ts: datetime
    end_ts: datetime
    total_fills: int
    total_volume: Decimal
    total_fees: Decimal
    realized_pnl: Decimal
    gross_spread_capture: Decimal
    net_spread_capture: Decimal
    fill_rate: Decimal
    avg_spread_captured_bps: Decimal
    inventory_turnover: Decimal


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


def calculate_mm_kpis(
    session: Session,
    account_name: str,
    start_ts: datetime,
    end_ts: datetime,
    initial_capital: Decimal,
) -> MMKPIResult:
    fills = session.execute(
        select(
            FillRecord.exchange,
            FillRecord.symbol,
            FillRecord.fill_price,
            FillRecord.fill_qty,
            FillRecord.fee_paid,
            FillRecord.fill_ts,
        )
        .select_from(FillRecord)
        .join(OrderRecord, OrderRecord.id == FillRecord.order_record_id)
        .join(OrderIntent, OrderIntent.id == OrderRecord.order_intent_id)
        .where(OrderIntent.mode == account_name)
        .where(FillRecord.fill_ts >= start_ts)
        .where(FillRecord.fill_ts <= end_ts)
        .order_by(FillRecord.fill_ts.asc())
    ).all()

    total_fills = len(fills)
    total_volume = Decimal("0")
    total_fees = Decimal("0")

    for exchange, symbol, fill_price, fill_qty, fee_paid, _fill_ts in fills:
        del exchange, symbol
        price = _to_decimal(fill_price)
        qty = _to_decimal(fill_qty)
        total_volume += price * qty
        total_fees += _to_decimal(fee_paid)

    realized_pnl = _to_decimal(
        session.execute(
            select(func.sum(PnLSnapshot.realized_pnl))
            .where(PnLSnapshot.strategy_name == account_name)
            .where(PnLSnapshot.snapshot_ts >= start_ts)
            .where(PnLSnapshot.snapshot_ts <= end_ts)
        ).scalar_one()
    )

    total_intents_generated = int(
        session.execute(
            select(func.count(OrderIntent.id))
            .where(OrderIntent.mode == account_name)
            .where(OrderIntent.created_ts >= start_ts)
            .where(OrderIntent.created_ts <= end_ts)
        ).scalar_one()
    )

    gross_spread_capture = Decimal("0")
    for exchange, symbol, fill_price, fill_qty, _fee_paid, fill_ts in fills:
        window_start = fill_ts - timedelta(seconds=5)
        window_end = fill_ts + timedelta(seconds=5)

        nearby_snapshots = session.execute(
            select(OrderBookSnapshot.event_ts, OrderBookSnapshot.mid_price)
            .where(OrderBookSnapshot.exchange == exchange)
            .where(OrderBookSnapshot.symbol == symbol)
            .where(OrderBookSnapshot.event_ts >= window_start)
            .where(OrderBookSnapshot.event_ts <= window_end)
            .where(OrderBookSnapshot.mid_price.is_not(None))
        ).all()

        if not nearby_snapshots:
            continue

        nearest_mid = min(
            nearby_snapshots,
            key=lambda row: abs((row[0] - fill_ts).total_seconds()),
        )[1]
        if nearest_mid is None:
            continue

        price = _to_decimal(fill_price)
        qty = _to_decimal(fill_qty)
        gross_spread_capture += abs(price - _to_decimal(nearest_mid)) * qty

    net_spread_capture = gross_spread_capture - total_fees

    fill_rate = Decimal("0")
    if total_intents_generated > 0:
        fill_rate = Decimal(total_fills) / Decimal(total_intents_generated)

    avg_spread_captured_bps = Decimal("0")
    if total_volume != Decimal("0"):
        avg_spread_captured_bps = (gross_spread_capture / total_volume) * Decimal("10000")

    inventory_turnover = Decimal("0")
    if initial_capital != Decimal("0"):
        inventory_turnover = total_volume / initial_capital

    return MMKPIResult(
        account_name=account_name,
        start_ts=start_ts,
        end_ts=end_ts,
        total_fills=total_fills,
        total_volume=total_volume,
        total_fees=total_fees,
        realized_pnl=realized_pnl,
        gross_spread_capture=gross_spread_capture,
        net_spread_capture=net_spread_capture,
        fill_rate=fill_rate,
        avg_spread_captured_bps=avg_spread_captured_bps,
        inventory_turnover=inventory_turnover,
    )