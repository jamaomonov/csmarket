"""Reading the admin audit trail (writing is ``audit.record``)."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ValidationError
from csmarket.modules.admin.audit_schemas import AuditActor, AuditRow
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.users.api import User


async def list_audit(
    db: AsyncSession,
    *,
    action: str | None,
    target_type: str | None,
    target_id: str | None,
    actor_id: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[AuditRow], str | None]:
    """Audit rows newest first, keyset on ``(created_at DESC, id DESC)``; filters are exact.

    Raises:
        ValidationError: ``actor_id`` is not a UUID, or the cursor is not ours.
    """
    stmt = (
        select(AdminAuditLog, User.display_name)
        .join(User, User.id == AdminAuditLog.actor_user_id)
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .limit(limit + 1)
    )
    if action:
        stmt = stmt.where(AdminAuditLog.action == action)
    if target_type:
        stmt = stmt.where(AdminAuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AdminAuditLog.target_id == target_id)
    if actor_id:
        try:
            uuid.UUID(actor_id)
        except ValueError as exc:
            raise ValidationError("invalid actor_id", code="actor_id") from exc
        stmt = stmt.where(AdminAuditLog.actor_user_id == actor_id)
    if cursor is not None:
        stamp, last_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                AdminAuditLog.created_at < stamp,
                and_(AdminAuditLog.created_at == stamp, AdminAuditLog.id < last_id),
            )
        )
    rows = list((await db.execute(stmt)).all())
    page, more = rows[:limit], len(rows) > limit
    items = [
        AuditRow(
            id=row.id,
            created_at=row.created_at,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            actor=AuditActor(id=row.actor_user_id, display_name=name),
            payload=row.payload,
        )
        for row, name in page
    ]
    last = page[-1][0] if more else None
    return items, (encode_cursor(last.created_at, last.id) if last is not None else None)


__all__ = ["list_audit"]
