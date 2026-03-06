from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class PnLSnapshot(Base):
    __tablename__ = "pnl_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    strategy_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)

    realized_pnl: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    funding_pnl: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False, default=0)
    fee_pnl: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False, default=0)

    gross_pnl: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    net_pnl: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)

    snapshot_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)