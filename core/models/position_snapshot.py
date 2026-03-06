from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)

    instrument_type: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(20), nullable=False)

    quantity: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    avg_entry_price: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)
    mark_price: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)

    unrealized_pnl: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)

    leverage: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    margin_used: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)

    snapshot_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)