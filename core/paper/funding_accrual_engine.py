"""Funding accrual engine for perpetual positions.

Tracks hourly funding rate accruals and settlement at Coinbase Advanced
schedule (00:00 UTC and 12:00 UTC).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from core.models.funding_accrual import FundingAccrual
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.pnl_snapshot import PnLSnapshot
from core.utils.logging import get_logger

_log = get_logger(__name__)


class FundingAccrualEngine:
    """Manages funding accrual and settlement for perp positions."""

    @staticmethod
    def accrue_hourly(account_name: str, db: Session) -> None:
        """Accrue hourly funding for any open short perp position.
        
        Args:
            account_name: Paper account name (e.g., 'paper_dn')
            db: SQLAlchemy session
        
        Notes:
            - Queries the current ETH-PERP position for account_name
            - Fetches latest Coinbase Advanced funding rate
            - SHORT position:
                - Positive rate: accrual is INCOME (longs pay shorts)
                - Negative rate: accrual is a COST (shorts pay longs)
            - Stores accrual in FundingAccrual table with settled=False
        """
        # Find the open short ETH-PERP position
        position = (
            db.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.account_name == account_name)
                .where(PositionSnapshot.exchange == "coinbase_advanced")
                .where(PositionSnapshot.symbol == "ETH-PERP")
                .where(PositionSnapshot.side == "short")
                .where(PositionSnapshot.quantity > 0)
                .order_by(PositionSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .first()
        )
        
        if position is None:
            return
        
        # Get latest funding rate
        latest_funding = (
            db.execute(
                select(FundingRateSnapshot)
                .where(FundingRateSnapshot.exchange == "coinbase_advanced")
                .where(FundingRateSnapshot.symbol == "ETH-PERP")
                .order_by(FundingRateSnapshot.event_ts.desc())
            )
            .scalars()
            .first()
        )
        
        if latest_funding is None:
            _log.warning("no_funding_rate_available", symbol="ETH-PERP")
            return
        
        # Calculate accrual
        position_qty = Decimal(str(position.quantity))
        mark_price = Decimal(str(position.mark_price)) if position.mark_price else Decimal("0")
        
        # Coinbase hourly rate needs to be used as-is for accrual calculation
        hourly_rate = Decimal(str(latest_funding.funding_rate))
        
        # Notional value: quantity * mark_price
        notional_usd = position_qty * mark_price
        
        # Accrual: for SHORT, positive rate is income, negative rate is cost
        # accrual = quantity * mark_price * hourly_rate (sign handles direction)
        accrual_usd = notional_usd * hourly_rate
        
        now = datetime.now(timezone.utc)
        
        accrual = FundingAccrual(
            account_name=account_name,
            exchange="coinbase_advanced",
            symbol="ETH-PERP",
            period_ts=latest_funding.event_ts,
            hourly_rate=hourly_rate,
            notional_usd=notional_usd,
            accrual_usd=accrual_usd,
            settled=False,
            created_ts=now,
        )
        db.add(accrual)
        
        _log.info(
            "funding_accrued",
            account_name=account_name,
            rate=str(hourly_rate),
            notional_usd=str(notional_usd),
            accrual_usd=str(accrual_usd),
        )

    @staticmethod
    def settle(account_name: str, db: Session) -> Decimal:
        """Settle all unsettled funding accruals.
        
        Args:
            account_name: Paper account name
            db: SQLAlchemy session
        
        Returns:
            Net settlement amount (positive = income, negative = cost)
        
        Notes:
            - Queries all unsettled FundingAccrual rows
            - Sums accrual_usd
            - Applies to total_funding_paid in PnLSnapshot
            - Marks all rows as settled=True
        """
        # Get all unsettled accruals for this account
        unsettled = db.execute(
            select(FundingAccrual)
            .where(FundingAccrual.account_name == account_name)
            .where(FundingAccrual.settled == False)
        ).scalars().all()
        
        if not unsettled:
            return Decimal("0")
        
        # Sum accrual amounts
        total_accrual = sum(
            Decimal(str(accrual.accrual_usd)) for accrual in unsettled
        )
        
        # Update PnLSnapshot: add to funding_pnl (or create if doesn't exist)
        pnl_snapshot = (
            db.execute(
                select(PnLSnapshot)
                .where(PnLSnapshot.strategy_name == account_name)
                .order_by(PnLSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .first()
        )
        
        if pnl_snapshot is not None:
            current_funding = Decimal(str(pnl_snapshot.funding_pnl)) if pnl_snapshot.funding_pnl else Decimal("0")
            pnl_snapshot.funding_pnl = current_funding + total_accrual
        
        # Mark all as settled
        for accrual in unsettled:
            accrual.settled = True
        
        now = datetime.now(timezone.utc)
        
        _log.info(
            "funding_settled",
            account_name=account_name,
            total_accrual=str(total_accrual),
            settlement_ts=now.isoformat(),
            accrual_count=len(unsettled),
        )
        
        return total_accrual

    @staticmethod
    def should_settle(now: datetime | None = None) -> bool:
        """Check if current time is within settlement window.
        
        Coinbase Advanced settles funding at:
        - 00:00 UTC (within 5 min window → 23:55 to 00:05)
        - 12:00 UTC (within 5 min window → 11:55 to 12:05)
        
        Args:
            now: Current datetime (defaults to now in UTC)
        
        Returns:
            True if within 5 minutes of a settlement time
        """
        if now is None:
            now = datetime.now(timezone.utc)
        
        hour = now.hour
        minute = now.minute
        
        # Check if within 5 minutes of 00:00 UTC
        if hour == 23 and minute >= 55:
            return True
        if hour == 0 and minute <= 5:
            return True
        
        # Check if within 5 minutes of 12:00 UTC
        if hour == 11 and minute >= 55:
            return True
        if hour == 12 and minute <= 5:
            return True
        
        return False
