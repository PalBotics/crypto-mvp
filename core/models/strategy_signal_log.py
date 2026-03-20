from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class StrategySignalLog(Base):
    __tablename__ = "strategy_signal_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)
    signal: Mapped[str] = mapped_column(String(50), nullable=False)
    funding_rate_apr: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    eth_mark_price: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    created_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
