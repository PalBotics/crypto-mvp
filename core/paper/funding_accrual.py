from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.funding_payment import FundingPayment
from core.models.position_snapshot import PositionSnapshot


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
