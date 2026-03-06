from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Index, Integer, Numeric, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class FundingRateSnapshot(Base):
    __tablename__ = "funding_rate_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_symbol: Mapped[str] = mapped_column(String(50), nullable=False)

    funding_rate: Mapped[float] = mapped_column(Numeric(18, 10), nullable=False)
    funding_interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_funding_rate: Mapped[float | None] = mapped_column(Numeric(18, 10), nullable=True)
    mark_price: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)
    index_price: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)
    next_funding_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index(
    "ix_funding_rate_snapshots_exchange_symbol_event_ts",
    FundingRateSnapshot.exchange,
    FundingRateSnapshot.symbol,
    FundingRateSnapshot.event_ts.desc(),
)