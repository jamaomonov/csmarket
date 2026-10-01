"""``fx_snapshots`` — every CBU USD/UZS rate we priced with (spec §5)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base


class FxSnapshot(Base):
    """One rate as fetched. Orders (M4) point at the row they were priced with."""

    __tablename__ = "fx_snapshots"
    __table_args__ = (
        CheckConstraint("usd_uzs > 0", name="usd_uzs_positive"),
        Index("ix_fx_snapshots_fetched_at", "fetched_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    usd_uzs: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
