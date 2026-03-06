from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class StrategySignal(Base):
    __tablename__ = "strategy_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    signal_strength: Mapped[float | None] = mapped_column(Numeric(18, 10), nullable=True)
    decision_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)