"""SQLAlchemy ORM for the ``admin`` module.

- :class:`AdminAuditLog` — one row per admin action (spec §5, ruling Q5). Written only by
  :func:`csmarket.modules.admin.audit.record`; there is no audit UI yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base


class AdminAuditLog(Base):
    """Who (``actor_user_id``) did what (``action``) to which thing (``target_*``)."""

    __tablename__ = "admin_audit_log"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    #: Dotted ``<module>.<thing>.<verb>``, e.g. ``skins.item.hide``.
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Names of things (slugs, aliases), never people — see ``audit.record``.
    # Any: a JSON object of scalar values.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_admin_audit_log_created_at", "created_at"),
        Index("ix_admin_audit_log_target", "target_type", "target_id"),
    )


__all__ = ["AdminAuditLog"]
