from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class FillRecord(Base):
    __tablename__ = "fill_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("order_records.id"),
        nullable=True,
    )

    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_trade_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    side: Mapped[str] = mapped_column(String(20), nullable=False)
    fill_price: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    fill_qty: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    fill_notional: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)

    liquidity_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fee_paid: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False, default=0)
    fee_asset: Mapped[str | None] = mapped_column(String(20), nullable=True)

    fill_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)