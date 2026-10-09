"""Admin API keys: list with sales, a key's card, the tariff switch, revoke (plan C, Task 4).

Reads are fixed-size statements (stats are one grouped join). Writes lock the key row, change
it, audit it (``api_keys.tariff`` / ``api_keys.revoke``; payloads carry the reason and the
tariff, never the token or the owner's identity) and leave the replay + commit to the route.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from urllib.parse import urlsplit

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.modules.admin.api_keys_schemas import (
    AdminApiKeyCard,
    AdminApiKeyDelivery,
    AdminApiKeyRow,
    AdminApiKeyWebhook,
    AdminKeyLimits,
    Tariff,
)
from csmarket.modules.admin.audit import record
from csmarket.modules.admin.orders_schemas import AdminOrderUser
from csmarket.modules.admin.orders_service import recent_key_orders
from csmarket.modules.admin.users_service import remember, replayed
from csmarket.modules.orders.api import Order
from csmarket.modules.public_api.api import (
    LIMIT_COLUMNS,
    ApiKey,
    ApiWebhook,
    ApiWebhookDelivery,
    effective_limits,
    revoke_key,
    set_pricing_profile,
)
from csmarket.modules.users.api import User

_CENT = Decimal("0.001")

__all__ = ["remember", "replayed"]


def _usd(value: Decimal | None) -> str:
    """Dollars with three decimals, no exponent."""
    return format((value or Decimal(0)).quantize(_CENT), "f")


def _like_escape(needle: str) -> str:
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _sales(
    db: AsyncSession, key_ids: Sequence[str]
) -> dict[str, tuple[int, Decimal, Decimal]]:
    """``(orders, revenue, cost)`` per key id, for these keys only.

    Revenue and cost both skip refunded orders; ``orders`` counts every order of the key.
    """
    if not key_ids:
        return {}
    unrefunded = Order.refunded_at.is_(None)
    stmt = (
        select(
            Order.api_key_id,
            func.count(),
            func.coalesce(func.sum(case((unrefunded, Order.price_usd), else_=0)), 0),
            func.coalesce(func.sum(case((unrefunded, Order.cost_usd), else_=0)), 0),
        )
        .where(Order.channel == "api", Order.api_key_id.in_(key_ids))
        .group_by(Order.api_key_id)
    )
    return {
        str(kid): (int(n), Decimal(rev), Decimal(cost))
        for kid, n, rev, cost in (await db.execute(stmt)).all()
    }


def _row(
    key: ApiKey, name: str | None, sales: tuple[int, Decimal, Decimal] | None
) -> AdminApiKeyRow:
    orders, revenue, cost = sales or (0, Decimal(0), Decimal(0))
    limits = effective_limits(key)
    return AdminApiKeyRow(
        id=key.id,
        user=AdminOrderUser(id=key.user_id, display_name=name),
        pricing_profile=key.pricing_profile,  # type: ignore[arg-type]  # CHECK-constrained
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        orders=orders,
        revenue_usd=_usd(revenue),
        cost_usd=_usd(cost),
        limits=AdminKeyLimits(
            read_per_min=limits["read"],
            orders_per_min=limits["order"],
            feed_per_min=limits["feed"],
            check_per_min=limits["check"],
        ),
        custom_limits=[c for c in LIMIT_COLUMNS.values() if getattr(key, c) is not None],
        ip_allowlist=list(key.ip_allowlist),
    )


async def list_keys(
    db: AsyncSession, *, q: str | None, cursor: str | None, limit: int
) -> tuple[list[AdminApiKeyRow], str | None]:
    """Live keys first, then revoked, each newest first (keyset on ``(revoked, created, id)``).

    ``q`` = part of the owner's display name.
    """
    stmt = select(ApiKey, User.display_name).join(User, User.id == ApiKey.user_id)
    revoked = (ApiKey.revoked_at.is_not(None)).label("rev")
    stmt = stmt.order_by(revoked, ApiKey.created_at.desc(), ApiKey.id.desc()).limit(limit + 1)
    needle = (q or "").strip()
    if needle:
        stmt = stmt.where(User.display_name.ilike(f"%{_like_escape(needle)}%", escape="\\"))
    if cursor is not None:
        stamp, last_id = decode_cursor(cursor)
        last = await db.get(ApiKey, last_id)
        if last is None:
            raise ValidationError("invalid cursor", code="cursor")
        last_rev = last.revoked_at is not None
        same = and_(
            ApiKey.revoked_at.is_not(None) == last_rev,
            or_(ApiKey.created_at < stamp, and_(ApiKey.created_at == stamp, ApiKey.id < last_id)),
        )
        stmt = stmt.where(or_(same, ApiKey.revoked_at.is_not(None)) if not last_rev else same)
    rows = list((await db.execute(stmt)).all())
    page, more = rows[:limit], len(rows) > limit
    sales = await _sales(db, [k.id for k, _ in page])
    items = [_row(k, n, sales.get(k.id)) for k, n in page]
    tail = page[-1][0] if more else None
    return items, (encode_cursor(tail.created_at, tail.id) if tail is not None else None)


async def get_key(db: AsyncSession, key_id: str, *, lock: bool = False) -> ApiKey:
    """The key by id; ``lock`` re-reads it ``FOR UPDATE``.

    Raises:
        NotFoundError: no such key, or ``key_id`` is not a UUID.
    """
    try:
        uuid.UUID(key_id)
    except ValueError as exc:
        raise NotFoundError("API key not found") from exc
    stmt = select(ApiKey).where(ApiKey.id == key_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    key = (await db.execute(stmt)).scalar_one_or_none()
    if key is None:
        raise NotFoundError("API key not found")
    return key


async def _webhook(db: AsyncSession, user_id: str) -> AdminApiKeyWebhook | None:
    hook = await db.get(ApiWebhook, user_id)
    if hook is None:
        return None
    last = (
        await db.execute(
            select(ApiWebhookDelivery)
            .where(ApiWebhookDelivery.user_id == user_id)
            .order_by(ApiWebhookDelivery.created_at.desc(), ApiWebhookDelivery.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    delivery = (
        AdminApiKeyDelivery.model_validate(last, from_attributes=True) if last is not None else None
    )
    return AdminApiKeyWebhook(host=urlsplit(hook.url).hostname or "", last_delivery=delivery)


async def key_card(db: AsyncSession, key: ApiKey) -> AdminApiKeyCard:
    """The row, the latest 20 orders and the owner's webhook (host only)."""
    name = await db.scalar(select(User.display_name).where(User.id == key.user_id))
    sales = await _sales(db, [key.id])
    return AdminApiKeyCard(
        key=_row(key, name, sales.get(key.id)),
        orders=await recent_key_orders(db, key.id),
        webhook=await _webhook(db, key.user_id),
    )


async def set_tariff(
    db: AsyncSession, *, admin: User, key: ApiKey, profile: Tariff, reason: str
) -> None:
    """Switch the tariff of a live key; audited ``api_keys.tariff``.

    Raises:
        ConflictError: ``api_key_revoked``; ``tariff_unchanged`` -- already on that tariff.
    """
    before = key.pricing_profile
    if key.revoked_at is None and before == profile:
        raise ConflictError("the key is already on this tariff", code="tariff_unchanged")
    await set_pricing_profile(db, key=key, profile=profile)
    await record(
        db,
        actor_id=admin.id,
        action="api_keys.tariff",
        target_type="api_key",
        target_id=key.id,
        payload={"from": before, "to": profile, "reason": reason},
    )


async def set_limits(
    db: AsyncSession, *, admin: User, key: ApiKey, values: dict[str, int | None], reason: str
) -> None:
    """Set the key's four limits (``None`` = the default); audited ``api_keys.limits``.

    ``values`` is keyed by column name (``read_per_min`` ...).

    Raises:
        ConflictError: ``api_key_revoked``; ``limits_unchanged`` -- nothing differs.
    """
    if key.revoked_at is not None:
        raise ConflictError("the API key is revoked", code="api_key_revoked")
    columns = list(LIMIT_COLUMNS.values())
    before = {c: getattr(key, c) for c in columns}
    after = {c: values[c] for c in columns}
    if before == after:
        raise ConflictError("the limits are already set so", code="limits_unchanged")
    for column, value in after.items():
        setattr(key, column, value)
    await record(
        db,
        actor_id=admin.id,
        action="api_keys.limits",
        target_type="api_key",
        target_id=key.id,
        payload={"from": before, "to": after, "reason": reason},
    )


async def revoke(db: AsyncSession, *, admin: User, key: ApiKey, reason: str) -> None:
    """Revoke the key; audited ``api_keys.revoke``.

    Raises:
        ConflictError: ``api_key_revoked`` -- already revoked.
    """
    await revoke_key(db, key=key)
    await record(
        db,
        actor_id=admin.id,
        action="api_keys.revoke",
        target_type="api_key",
        target_id=key.id,
        payload={"reason": reason},
    )
