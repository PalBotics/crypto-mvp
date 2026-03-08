from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class OrderBookSnapshot(Base):
    """Top-of-book plus depth snapshot for market-making decisions."""

    __tablename__ = "order_book_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_symbol: Mapped[str] = mapped_column(String(50), nullable=False)

    bid_price_1: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    bid_size_1: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    ask_price_1: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    ask_size_1: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)

    bid_price_2: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    bid_size_2: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    ask_price_2: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    ask_size_2: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)

    bid_price_3: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    bid_size_3: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    ask_price_3: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    ask_size_3: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)

    spread: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    spread_bps: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    mid_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)

    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index(
    "ix_order_book_snapshots_exchange_symbol_event_ts",
    OrderBookSnapshot.exchange,
    OrderBookSnapshot.symbol,
    OrderBookSnapshot.event_ts.desc(),
)
