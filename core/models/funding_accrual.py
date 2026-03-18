from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class FundingAccrual(Base):
    __tablename__ = "funding_accruals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    
    period_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hourly_rate: Mapped[float] = mapped_column(Numeric(18, 10), nullable=False)
    notional_usd: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    accrual_usd: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    settled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
