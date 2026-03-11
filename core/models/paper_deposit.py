from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class PaperDeposit(Base):
    __tablename__ = "paper_deposits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    note: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
