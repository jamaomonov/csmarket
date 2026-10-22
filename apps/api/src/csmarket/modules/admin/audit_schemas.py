"""Wire shapes for ``GET /api/v1/admin/audit``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditActor(BaseModel):
    """The admin who acted."""

    id: str
    display_name: str | None


class AuditRow(BaseModel):
    """One ``admin_audit_log`` row."""

    id: str
    created_at: datetime
    #: Dotted ``<module>.<thing>.<verb>``, e.g. ``users.ban``.
    action: str
    target_type: str
    target_id: str
    #: A readable name for an id-only target — a user's or an API key owner's display name, a
    #: skin's market name, a payout's sale number; ``None`` when there is none (never PII).
    target_label: str | None = None
    actor: AuditActor
    #: What the action recorded (flat scalars: a reason, an amount, a slug); never PII.
    # Any: a JSON object of scalar values, stored as written by ``audit.record``.
    payload: dict[str, Any]


class AuditOut(BaseModel):
    """A page of audit rows, newest first, and the cursor for the next (``null`` on the last)."""

    items: list[AuditRow]
    next_cursor: str | None


__all__ = ["AuditActor", "AuditOut", "AuditRow"]
