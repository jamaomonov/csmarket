"""The admin audit trail: every admin write records one ``admin_audit_log`` row.

The caller records inside the same transaction as the change it audits, so the change and
its row commit (or roll back) together.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.admin.models import AdminAuditLog

#: What an audit payload may hold: flat scalars, JSON-ready.
AuditPayload = dict[str, str | int | bool | None]


async def record(
    db: AsyncSession,
    *,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    payload: AuditPayload | None = None,
) -> None:
    """Add one audit row and flush it; the caller commits.

    Payloads name things (slugs, aliases), never people: no Steam IDs, emails or IPs.

    Args:
        db: The request's session — the same transaction as the audited change.
        actor_id: ``users.id`` of the admin acting.
        action: Dotted ``<module>.<thing>.<verb>``, at most 64 characters.
        target_type: The kind of thing acted on (``skin_item``, ``skin_alias``).
        target_id: Its id or natural key, at most 64 characters.
        payload: Extra context, stored as a JSON object (``{}`` when omitted).
    """
    db.add(
        AdminAuditLog(
            id=new_id(),
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=dict(payload or {}),
            created_at=now(),
        )
    )
    await db.flush()


__all__ = ["AuditPayload", "record"]
