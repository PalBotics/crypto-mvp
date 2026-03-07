from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class FundingPayment(Base):
    __tablename__ = "funding_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)

    position_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    mark_price: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    funding_rate: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)

    accrued_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
