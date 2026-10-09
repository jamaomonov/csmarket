"""The partner's webhook URL: read, replace, delete (one per user)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.modules.public_api.models import ApiWebhook, ApiWebhookDelivery
from csmarket.modules.public_api.schemas import WebhookDeliveryOut, WebhookOut


async def get(db: AsyncSession, user_id: str) -> WebhookOut | None:
    """The user's webhook with its latest delivery, or ``None``."""
    row = await db.get(ApiWebhook, user_id)
    if row is None:
        return None
    last = (
        await db.execute(
            select(ApiWebhookDelivery)
            .where(ApiWebhookDelivery.user_id == user_id)
            .order_by(ApiWebhookDelivery.created_at.desc(), ApiWebhookDelivery.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return WebhookOut(
        url=row.url,
        created_at=row.created_at,
        last_delivery=None
        if last is None
        else WebhookDeliveryOut(
            event=last.event,
            status=last.status,
            attempts=last.attempts,
            last_status_code=last.last_status_code,
            at=last.sent_at or last.updated_at,
        ),
    )


async def put(db: AsyncSession, user_id: str, url: str) -> None:
    """Store ``url`` (already checked) for the user, replacing any earlier one."""
    stamp = now()
    stmt = insert(ApiWebhook).values(user_id=user_id, url=url, created_at=stamp, updated_at=stamp)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[ApiWebhook.user_id], set_={"url": url, "updated_at": stamp}
        )
    )


async def remove(db: AsyncSession, user_id: str) -> None:
    """Delete the user's webhook (a no-op when there is none)."""
    await db.execute(delete(ApiWebhook).where(ApiWebhook.user_id == user_id))
