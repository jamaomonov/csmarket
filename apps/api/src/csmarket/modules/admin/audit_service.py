"""Reading the admin audit trail (writing is ``audit.record``), with readable target names."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ValidationError
from csmarket.modules.admin.audit_schemas import AuditActor, AuditRow
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.public_api.api import ApiKey
from csmarket.modules.sales.api import PayoutRequest, Sale
from csmarket.modules.skins.api import SkinItem
from csmarket.modules.users.api import User


def _uuids(ids: Iterable[str]) -> list[str]:
    """The ids that are UUIDs (a hand-written row never reaches a UUID column as text)."""
    out = []
    for raw in ids:
        try:
            out.append(str(uuid.UUID(raw)))
        except ValueError:
            continue
    return out


def _label_query(target_type: str, ids: list[str]) -> Select[str, str | None] | None:
    """``(id, label)`` of one id-only target type; ``None`` for a type that names itself."""
    match target_type:
        case "user":
            return select(User.id, User.display_name).where(User.id.in_(ids))
        case "skin_item":
            return select(SkinItem.id, SkinItem.market_hash_name).where(SkinItem.id.in_(ids))
        case "payout_request":
            return (
                select(PayoutRequest.id, Sale.number)
                .join(Sale, Sale.id == PayoutRequest.sale_id)
                .where(PayoutRequest.id.in_(ids))
            )
        case "api_key":
            return (
                select(ApiKey.id, User.display_name)
                .join(User, User.id == ApiKey.user_id)
                .where(ApiKey.id.in_(ids))
            )
        case _:
            return None


async def _target_labels(db: AsyncSession, rows: list[AdminAuditLog]) -> dict[tuple[str, str], str]:
    """Readable names of a page's id-only targets: one query per target type on the page."""
    wanted: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        wanted[row.target_type].add(row.target_id)
    labels: dict[tuple[str, str], str] = {}
    for target_type, ids in wanted.items():
        uuids = _uuids(ids)
        stmt = _label_query(target_type, uuids) if uuids else None
        if stmt is None:
            continue
        for target_id, label in (await db.execute(stmt)).all():
            if label:
                labels[(target_type, str(target_id))] = label
    return labels


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
    labels = await _target_labels(db, [row for row, _ in page])
    items = [
        AuditRow(
            id=row.id,
            created_at=row.created_at,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            target_label=labels.get((row.target_type, row.target_id)),
            actor=AuditActor(id=row.actor_user_id, display_name=name),
            payload=row.payload,
        )
        for row, name in page
    ]
    last = page[-1][0] if more else None
    return items, (encode_cursor(last.created_at, last.id) if last is not None else None)


__all__ = ["list_audit"]
