from __future__ import annotations

from decimal import Decimal

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from core.models.fill_record import FillRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot


def _signed_qty(side: str, qty: Decimal) -> Decimal:
    side_normalized = side.strip().lower()
    if side_normalized == "buy":
        return qty
    if side_normalized == "sell":
        return -qty
    raise ValueError(f"Unsupported side for PnL accounting: {side}")


def _decimal_or_zero(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _compute_realized_pnl(fill_record: FillRecord, position_snapshot: PositionSnapshot) -> Decimal:
    fill_qty = _decimal_or_zero(fill_record.fill_qty)
    fill_price = _decimal_or_zero(fill_record.fill_price)
    fill_signed = _signed_qty(fill_record.side, fill_qty)

    state = inspect(position_snapshot)
    side_history = state.attrs.side.history
    qty_history = state.attrs.quantity.history
    avg_history = state.attrs.avg_entry_price.history

    old_side = side_history.deleted[0] if side_history.deleted else position_snapshot.side
    old_qty = _decimal_or_zero(qty_history.deleted[0] if qty_history.deleted else position_snapshot.quantity)
    old_avg = _decimal_or_zero(
        avg_history.deleted[0] if avg_history.deleted else position_snapshot.avg_entry_price
    )

    old_signed = _signed_qty(old_side, old_qty) if old_qty != 0 else Decimal("0")

    if old_signed == 0 or (old_signed > 0 and fill_signed > 0) or (old_signed < 0 and fill_signed < 0):
        return Decimal("0")

    closing_qty = min(abs(old_signed), abs(fill_signed))

    if old_signed > 0:
        # Sell against an existing long.
        return (fill_price - old_avg) * closing_qty

    # Buy against an existing short.
    return (old_avg - fill_price) * closing_qty


def _compute_unrealized_pnl(position_snapshot: PositionSnapshot, mark_price: Decimal) -> Decimal:
    qty = _decimal_or_zero(position_snapshot.quantity)
    avg_entry = position_snapshot.avg_entry_price
    if qty == 0 or avg_entry is None:
        return Decimal("0")

    avg = Decimal(str(avg_entry))
    side = position_snapshot.side.strip().lower()
    if side == "buy":
        return (mark_price - avg) * qty
    if side == "sell":
        return (avg - mark_price) * qty
    raise ValueError(f"Unsupported position side for unrealized PnL: {position_snapshot.side}")


def create_pnl_snapshot_from_fill(
    session: Session,
    fill_record: FillRecord,
    position_snapshot: PositionSnapshot,
    mark_price: Decimal,
) -> PnLSnapshot:
    """Create and persist one PnL snapshot from a fill + updated position.

    The existing PnLSnapshot schema is reused directly. This function does not
    commit; transaction ownership remains with the caller.
    """
    realized = _compute_realized_pnl(fill_record, position_snapshot)
    unrealized = _compute_unrealized_pnl(position_snapshot, mark_price)
    gross = realized + unrealized

    snapshot = PnLSnapshot(
        portfolio_id=None,
        strategy_name=position_snapshot.account_name,
        symbol=fill_record.symbol,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=gross,
        net_pnl=gross,
        snapshot_ts=fill_record.fill_ts,
    )
    session.add(snapshot)
    return snapshot
