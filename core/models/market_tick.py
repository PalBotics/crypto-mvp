from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Index, Numeric, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class MarketTick(Base):
    __tablename__ = "market_ticks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_symbol: Mapped[str] = mapped_column(String(50), nullable=False)

    bid_price: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    ask_price: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    mid_price: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    last_price: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)
    bid_size: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)
    ask_size: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)

    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sequence_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


Index("ix_market_ticks_exchange_symbol_event_ts", MarketTick.exchange, MarketTick.symbol, MarketTick.event_ts.desc())
Index("ix_market_ticks_symbol_event_ts", MarketTick.symbol, MarketTick.event_ts.desc())