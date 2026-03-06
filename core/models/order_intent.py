from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class OrderIntent(Base):
    __tablename__ = "order_intents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_signal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_signals.id"),
        nullable=True,
    )
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    side: Mapped[str] = mapped_column(String(20), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    time_in_force: Mapped[str | None] = mapped_column(String(20), nullable=True)

    quantity: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)

    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    post_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    client_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)