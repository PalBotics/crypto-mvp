"""Hedge ratio calculator for delta-neutral trading strategies.

Computes hedge ratio between spot and perpetual positions, detecting
imbalance and logging drift warnings.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from core.models.market_tick import MarketTick
from core.models.position_snapshot import PositionSnapshot
from core.utils.logging import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class HedgeStatus:
    """Hedge ratio and position status."""
    spot_notional: Decimal
    perp_notional: Decimal
    hedge_ratio: Decimal
    spot_qty: Decimal
    perp_qty: Decimal
    mark_price: Decimal
    is_balanced: bool
    funding_rate_apr: Decimal = Decimal("0")
    daily_funding_accrued_usd: Decimal = Decimal("0")


def compute_hedge_ratio(account_name: str, db: Session) -> HedgeStatus:
    """Calculate hedge ratio between spot ETH and short ETH-PERP positions.
    
    Args:
        account_name: Paper account name (e.g., 'paper_dn')
        db: SQLAlchemy session
    
    Returns:
        HedgeStatus dataclass with notionals, ratio, and balance indicator
    
    Notes:
        - Queries spot ETH position (exchange=kraken, symbol=ETHUSD, side=long)
        - Queries perp ETH position (exchange=coinbase_advanced, symbol=ETH-PERP, side=short)
        - Gets latest ETH mark price from coinbase_advanced ticks
        - spot_notional = spot_quantity * eth_mark_price
        - perp_notional = abs(perp_quantity) * eth_mark_price
        - hedge_ratio = spot_notional / perp_notional (target: 1.0)
        - is_balanced = hedge_ratio between 0.9 and 1.1
        - Logs hedge_ratio_drift_warning if not balanced
    """
    # Get spot position (Kraken ETH)
    spot_position = (
        db.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.account_name == account_name)
            .where(PositionSnapshot.exchange == "kraken")
            .where(PositionSnapshot.symbol == "ETHUSD")
            .where(or_(PositionSnapshot.side == "long", PositionSnapshot.side == "buy"))
            .where(PositionSnapshot.quantity > 0)
            .order_by(PositionSnapshot.snapshot_ts.desc())
        )
        .scalars()
        .first()
    )
    
    # Get perp position (Coinbase ETH-PERP)
    perp_position = (
        db.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.account_name == account_name)
            .where(PositionSnapshot.exchange == "coinbase_advanced")
            .where(PositionSnapshot.symbol == "ETH-PERP")
            .where(or_(PositionSnapshot.side == "short", PositionSnapshot.side == "sell"))
            .where(PositionSnapshot.quantity > 0)
            .order_by(PositionSnapshot.snapshot_ts.desc())
        )
        .scalars()
        .first()
    )
    
    # Get latest ETH mark price
    latest_tick = (
        db.execute(
            select(MarketTick)
            .where(MarketTick.exchange == "coinbase_advanced")
            .where(MarketTick.symbol == "ETH-PERP")
            .order_by(MarketTick.event_ts.desc())
        )
        .scalars()
        .first()
    )
    
    if latest_tick is not None:
        mark_price = Decimal(str(latest_tick.mid_price))
    elif perp_position is not None and perp_position.mark_price is not None:
        mark_price = Decimal(str(perp_position.mark_price))
    elif spot_position is not None and spot_position.mark_price is not None:
        mark_price = Decimal(str(spot_position.mark_price))
    elif perp_position is not None and perp_position.avg_entry_price is not None:
        mark_price = Decimal(str(perp_position.avg_entry_price))
    elif spot_position is not None and spot_position.avg_entry_price is not None:
        mark_price = Decimal(str(spot_position.avg_entry_price))
    else:
        mark_price = Decimal("0")
    
    spot_qty = Decimal(str(spot_position.quantity)) if spot_position else Decimal("0")
    perp_qty = Decimal(str(perp_position.quantity)) if perp_position else Decimal("0")
    
    spot_notional = spot_qty * mark_price
    perp_notional = perp_qty * mark_price
    
    # Calculate hedge ratio: 1.0 means perfectly balanced
    if perp_notional == Decimal("0"):
        hedge_ratio = Decimal("0")
    else:
        hedge_ratio = spot_notional / perp_notional
    
    is_balanced = Decimal("0.9") <= hedge_ratio <= Decimal("1.1")
    
    _log.info(
        "hedge_ratio_computed",
        account_name=account_name,
        spot_notional=str(spot_notional),
        perp_notional=str(perp_notional),
        hedge_ratio=str(hedge_ratio),
        spot_qty=str(spot_qty),
        perp_qty=str(perp_qty),
        mark_price=str(mark_price),
        is_balanced=is_balanced,
    )
    
    if not is_balanced:
        _log.warning(
            "hedge_ratio_drift_warning",
            account_name=account_name,
            hedge_ratio=str(hedge_ratio),
            spot_notional=str(spot_notional),
            perp_notional=str(perp_notional),
        )
    
    return HedgeStatus(
        spot_notional=spot_notional,
        perp_notional=perp_notional,
        hedge_ratio=hedge_ratio,
        spot_qty=spot_qty,
        perp_qty=perp_qty,
        mark_price=mark_price,
        is_balanced=is_balanced,
    )
