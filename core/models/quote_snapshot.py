from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class QuoteSnapshot(Base):
    __tablename__ = "quote_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)

    snapshot_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    twap: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    mid_price: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    bid_quote: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    ask_quote: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    twap_lookback_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    spread_bps: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)


Index("ix_quote_snapshots_snapshot_ts", QuoteSnapshot.snapshot_ts)
Index(
    "ix_quote_snapshots_exchange_symbol_account_snapshot_ts",
    QuoteSnapshot.exchange,
    QuoteSnapshot.symbol,
    QuoteSnapshot.account_name,
    QuoteSnapshot.snapshot_ts.desc(),
)
