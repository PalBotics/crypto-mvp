from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class OrderRecord(Base):
    __tablename__ = "order_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("order_intents.id"),
        nullable=True,
    )

    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    client_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    side: Mapped[str] = mapped_column(String(20), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    submitted_price: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)
    submitted_qty: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    filled_qty: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False, default=0)
    avg_fill_price: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)

    fees_paid: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False, default=0)
    fee_asset: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_exchange_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)