from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    details_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)