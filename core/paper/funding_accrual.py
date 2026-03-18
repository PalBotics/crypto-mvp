from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.funding_accrual import FundingAccrual
from core.models.funding_payment import FundingPayment
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.utils.logging import get_logger

_log = get_logger(__name__)


def accrue_funding_payment(
    session: Session,
    symbol: str,
    exchange: str,
    account_name: str,
    mark_price: Decimal,
    funding_rate: Decimal,
) -> FundingPayment | None:
    """Calculate and persist one funding payment for an open position.

    Returns None if no open position exists for (exchange, symbol, account_name).
    Does not commit; transaction ownership remains with the caller.

    Payment direction:
        payment_amount = -1 * position_quantity * mark_price * funding_rate
        Negative -> trader paid (long + positive rate).
        Positive -> trader received (long + negative rate).
    """
    position = (
        session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.exchange == exchange)
            .where(PositionSnapshot.symbol == symbol)
            .where(PositionSnapshot.account_name == account_name)
            .where(PositionSnapshot.quantity > 0)
            .order_by(PositionSnapshot.snapshot_ts.desc())
        )
        .scalars()
        .first()
    )

    if position is None:
        return None

    position_quantity = Decimal(str(position.quantity))
    payment_amount = Decimal("-1") * position_quantity * mark_price * funding_rate

    now = datetime.now(timezone.utc)
    payment = FundingPayment(
        exchange=exchange,
        symbol=symbol,
        account_name=account_name,
        position_quantity=position_quantity,
        mark_price=mark_price,
        funding_rate=funding_rate,
        payment_amount=payment_amount,
        accrued_ts=now,
        created_ts=now,
    )
    session.add(payment)
    return payment


class FundingAccrualEngine:
    """Tracks hourly funding accruals and settles twice daily."""

    @staticmethod
    def accrue_hourly(account_name: str, db: Session) -> None:
        position = (
            db.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.account_name == account_name)
                .where(PositionSnapshot.exchange == "coinbase_advanced")
                .where(PositionSnapshot.symbol == "ETH-PERP")
                .where(PositionSnapshot.side == "short")
                .where(PositionSnapshot.position_type == "perp")
                .where(PositionSnapshot.quantity > 0)
                .order_by(PositionSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .first()
        )
        if position is None:
            return

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
            return

        quantity = Decimal(str(position.quantity))
        mark_price = (
            Decimal(str(position.mark_price))
            if position.mark_price is not None
            else Decimal(str(latest_funding.mark_price or 0))
        )
        hourly_rate = Decimal(str(latest_funding.funding_rate))
        notional_usd = quantity * mark_price
        accrual_usd = notional_usd * hourly_rate

        db.add(
            FundingAccrual(
                account_name=account_name,
                exchange="coinbase_advanced",
                symbol="ETH-PERP",
                period_ts=latest_funding.event_ts,
                hourly_rate=hourly_rate,
                notional_usd=notional_usd,
                accrual_usd=accrual_usd,
                settled=False,
                created_ts=datetime.now(timezone.utc),
            )
        )
        _log.info(
            "funding_accrued",
            account_name=account_name,
            rate=str(hourly_rate),
            notional=str(notional_usd),
            accrual_usd=str(accrual_usd),
        )

    @staticmethod
    def settle(account_name: str, db: Session) -> Decimal:
        unsettled = (
            db.execute(
                select(FundingAccrual)
                .where(FundingAccrual.account_name == account_name)
                .where(FundingAccrual.settled.is_(False))
            )
            .scalars()
            .all()
        )
        if not unsettled:
            return Decimal("0")

        total_accrual = sum(Decimal(str(x.accrual_usd)) for x in unsettled)
        pnl = (
            db.execute(
                select(PnLSnapshot)
                .where(PnLSnapshot.strategy_name == account_name)
                .order_by(PnLSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .first()
        )
        if pnl is not None:
            pnl.funding_pnl = Decimal(str(pnl.funding_pnl or 0)) + total_accrual

        for row in unsettled:
            row.settled = True

        _log.info(
            "funding_settled",
            account_name=account_name,
            total_accrual=str(total_accrual),
            settlement_ts=datetime.now(timezone.utc).isoformat(),
        )
        return total_accrual

    @staticmethod
    def should_settle(now: datetime | None = None) -> bool:
        now_utc = now if now is not None else datetime.now(timezone.utc)
        hour = now_utc.hour
        minute = now_utc.minute
        if hour == 23 and minute >= 55:
            return True
        if hour == 0 and minute <= 5:
            return True
        if hour == 11 and minute >= 55:
            return True
        if hour == 12 and minute <= 5:
            return True
        return False
