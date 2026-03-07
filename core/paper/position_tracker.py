from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.fill_record import FillRecord
from core.models.position_snapshot import PositionSnapshot


def _signed_qty(side: str, qty: Decimal) -> Decimal:
    side_normalized = side.strip().lower()
    if side_normalized == "buy":
        return qty
    if side_normalized == "sell":
        return -qty
    raise ValueError(f"Unsupported fill side for position tracking: {side}")


def update_position_from_fill(
    session: Session,
    fill_record: FillRecord,
    mode: str = "paper",
) -> PositionSnapshot:
    """Create or update a position snapshot from a persisted fill.

    Notes:
        The existing PositionSnapshot schema does not include explicit mode/status
        fields. This tracker stores `mode` in `account_name` and treats a
        position as closed when quantity reaches zero.
    """
    existing = (
        session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.exchange == fill_record.exchange)
            .where(PositionSnapshot.symbol == fill_record.symbol)
            .where(PositionSnapshot.account_name == mode)
            .order_by(PositionSnapshot.snapshot_ts.desc())
        )
        .scalars()
        .first()
    )

    fill_qty = Decimal(str(fill_record.fill_qty))
    fill_price = Decimal(str(fill_record.fill_price))
    fill_signed = _signed_qty(fill_record.side, fill_qty)

    if existing is None:
        position = PositionSnapshot(
            exchange=fill_record.exchange,
            account_name=mode,
            symbol=fill_record.symbol,
            instrument_type="spot",
            side=fill_record.side,
            quantity=fill_qty,
            avg_entry_price=fill_price,
            mark_price=fill_price,
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            leverage=None,
            margin_used=None,
            snapshot_ts=fill_record.fill_ts,
        )
        session.add(position)
        return position

    existing_qty = Decimal(str(existing.quantity))
    existing_avg = (
        Decimal(str(existing.avg_entry_price))
        if existing.avg_entry_price is not None
        else Decimal("0")
    )
    existing_signed = _signed_qty(existing.side, existing_qty)

    new_signed = existing_signed + fill_signed

    if new_signed == 0:
        existing.quantity = Decimal("0")
        existing.avg_entry_price = None
    elif existing_signed == 0 or (existing_signed > 0 and fill_signed > 0) or (
        existing_signed < 0 and fill_signed < 0
    ):
        new_qty = abs(new_signed)
        new_avg = ((existing_qty * existing_avg) + (fill_qty * fill_price)) / new_qty
        existing.quantity = new_qty
        existing.avg_entry_price = new_avg
        existing.side = fill_record.side
    elif abs(fill_signed) < abs(existing_signed):
        # Partial reduction keeps the original entry for remaining quantity.
        existing.quantity = abs(new_signed)
    else:
        # Reversal opens the residual quantity at the latest fill price.
        existing.quantity = abs(new_signed)
        existing.avg_entry_price = fill_price
        existing.side = fill_record.side

    existing.mark_price = fill_price
    existing.snapshot_ts = fill_record.fill_ts

    return existing
