"""Perpetual position execution and fill recording.

Handles opening and closing perp positions with proper accounting for
contract quantities, margin posting, and realized PnL calculation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.fill_record import FillRecord
from core.models.position_snapshot import PositionSnapshot
from core.utils.logging import get_logger

_log = get_logger(__name__)


def open_perp_short(
    session: Session,
    account_name: str,
    exchange: str,
    symbol: str,
    contract_qty: int,
    mark_price: Decimal,
    margin_rate: Decimal = Decimal("0.10"),
) -> PositionSnapshot:
    """Open a short perpetual position.
    
    Args:
        session: SQLAlchemy session
        account_name: Paper account name (e.g., 'paper_dn')
        exchange: Exchange name (e.g., 'coinbase_advanced')
        symbol: Symbol (e.g., 'ETH-PERP')
        contract_qty: Number of contracts (each = contract_size ETH)
        mark_price: Entry price = current mark price
        margin_rate: Margin rate (default 10% initial margin)
    
    Returns:
        PositionSnapshot for the new short position
    
    Notes:
        - quantity = contract_qty * 0.10 (for ETH-PERP, each contract = 0.10 ETH)
        - margin_posted = quantity * mark_price * margin_rate
        - Records a fill with side='short'
    """
    quantity = Decimal(contract_qty) * Decimal("0.10")
    margin_posted = quantity * mark_price * margin_rate
    
    now = datetime.now(timezone.utc)
    
    # Create fill record first
    fill = FillRecord(
        order_record_id=None,
        exchange=exchange,
        symbol=symbol,
        exchange_trade_id=None,
        side="short",
        fill_price=mark_price,
        fill_qty=quantity,
        fill_notional=quantity * mark_price,
        liquidity_role="paper_fill",
        fee_paid=Decimal("0"),
        fee_asset=None,
        fill_ts=now,
        ingested_ts=now,
    )
    session.add(fill)
    session.flush()
    
    existing = (
        session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.exchange == exchange)
            .where(PositionSnapshot.symbol == symbol)
            .where(PositionSnapshot.account_name == account_name)
            .where(PositionSnapshot.position_type == "perp")
            .where(PositionSnapshot.side == "short")
            .where(PositionSnapshot.quantity > 0)
            .order_by(PositionSnapshot.snapshot_ts.desc())
        )
        .scalars()
        .first()
    )

    existing_qty: Decimal | None = None
    existing_avg: Decimal | None = None
    if existing is not None:
        try:
            existing_qty = Decimal(str(existing.quantity))
            existing_avg = Decimal(str(existing.avg_entry_price or 0))
        except (AttributeError, InvalidOperation):
            existing = None

    if existing is None:
        position = PositionSnapshot(
            exchange=exchange,
            account_name=account_name,
            symbol=symbol,
            instrument_type="perpetual",
            side="short",
            position_type="perp",
            quantity=quantity,
            avg_entry_price=mark_price,
            mark_price=mark_price,
            contract_qty=contract_qty,
            contract_size=Decimal("0.10"),
            margin_posted=margin_posted,
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            leverage=None,
            margin_used=margin_posted,
            snapshot_ts=now,
        )
        session.add(position)
    else:
        assert existing_qty is not None
        assert existing_avg is not None
        new_qty = existing_qty + quantity
        new_avg = ((existing_qty * existing_avg) + (quantity * mark_price)) / new_qty
        existing.quantity = new_qty
        existing.avg_entry_price = new_avg
        existing.mark_price = mark_price
        existing.contract_qty = int(existing.contract_qty or 0) + contract_qty
        existing.contract_size = Decimal("0.10")
        existing.margin_posted = Decimal(str(existing.margin_posted or 0)) + margin_posted
        existing.margin_used = Decimal(str(existing.margin_used or 0)) + margin_posted
        existing.snapshot_ts = now
        position = existing
    
    _log.info(
        "perp_position_opened",
        account_name=account_name,
        exchange=exchange,
        symbol=symbol,
        contract_qty=contract_qty,
        quantity=str(quantity),
        entry_price=str(mark_price),
        margin_posted=str(margin_posted),
    )
    
    return position


def close_perp_short(
    session: Session,
    account_name: str,
    exchange: str,
    symbol: str,
    mark_price: Decimal,
    contract_qty: int | None = None,
) -> Decimal:
    """Close a short perpetual position.
    
    Args:
        session: SQLAlchemy session
        account_name: Paper account name
        exchange: Exchange name
        symbol: Symbol
        mark_price: Exit price = current mark price
    
    Returns:
        Realized PnL (positive = profit for short position)
    
    Notes:
        - For SHORT: realized_pnl = (entry_price - exit_price) * quantity
        - Returns margin_posted to cash balance
        - Records a fill with side='long' (buying back the short)
    """
    # Find existing position
    position = (
        session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.exchange == exchange)
            .where(PositionSnapshot.symbol == symbol)
            .where(PositionSnapshot.account_name == account_name)
            .where(PositionSnapshot.position_type == "perp")
            .where(PositionSnapshot.side == "short")
            .where(PositionSnapshot.quantity > 0)
            .order_by(PositionSnapshot.snapshot_ts.desc())
        )
        .scalars()
        .first()
    )
    
    if position is None:
        _log.warning(
            "no_open_perp_position",
            account_name=account_name,
            exchange=exchange,
            symbol=symbol,
        )
        return Decimal("0")
    
    entry_price = Decimal(str(position.avg_entry_price))
    quantity = Decimal(str(position.quantity))
    margin_posted = Decimal(str(position.margin_posted)) if position.margin_posted else Decimal("0")
    
    close_qty = quantity
    if contract_qty is not None and contract_qty > 0:
        requested_qty = Decimal(contract_qty) * Decimal("0.10")
        close_qty = requested_qty if requested_qty < quantity else quantity

    # Calculate realized PnL: for short, profit when price falls
    realized_pnl = (entry_price - mark_price) * close_qty
    
    now = datetime.now(timezone.utc)
    
    # Create closing fill (buying back the short)
    fill = FillRecord(
        order_record_id=None,
        exchange=exchange,
        symbol=symbol,
        exchange_trade_id=None,
        side="long",
        fill_price=mark_price,
        fill_qty=close_qty,
        fill_notional=close_qty * mark_price,
        liquidity_role="paper_fill",
        fee_paid=Decimal("0"),
        fee_asset=None,
        fill_ts=now,
        ingested_ts=now,
    )
    session.add(fill)
    session.flush()
    
    margin_returned = Decimal("0")
    if quantity > 0 and margin_posted > 0:
        margin_returned = (close_qty / quantity) * margin_posted

    remaining_qty = quantity - close_qty
    # Update position: full close or partial close
    position.quantity = remaining_qty
    if remaining_qty == 0:
        position.avg_entry_price = None
        position.contract_qty = 0
    else:
        position.contract_qty = int(remaining_qty / Decimal("0.10"))
    position.mark_price = mark_price
    position.realized_pnl = Decimal(str(position.realized_pnl or 0)) + realized_pnl
    position.margin_posted = Decimal(str(position.margin_posted or 0)) - margin_returned
    position.margin_used = Decimal(str(position.margin_used or 0)) - margin_returned
    position.snapshot_ts = now
    
    _log.info(
        "perp_position_closed",
        account_name=account_name,
        exchange=exchange,
        symbol=symbol,
        exit_price=str(mark_price),
        realized_pnl=str(realized_pnl),
        margin_returned=str(margin_returned),
        close_qty=str(close_qty),
    )
    
    return realized_pnl
