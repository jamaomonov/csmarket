"""Kassa limits: the admin's read and audited save (``If-Match`` like «Настройки оплаты»)."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, ValidationError
from csmarket.core.money import wire_uzs
from csmarket.modules.admin.api import AuditPayload, record
from csmarket.modules.risk.models import KassaReviewLimit
from csmarket.modules.risk.schemas import AuthorOut, KassaLimitOut, ReviewLimitsIn, ReviewLimitsOut
from csmarket.modules.users.api import User


async def _version(db: AsyncSession) -> datetime | None:
    return await db.scalar(select(func.max(KassaReviewLimit.updated_at)))


async def limits_view(db: AsyncSession) -> ReviewLimitsOut:
    """Every kassa's limit, the newest save and its author."""
    stmt = (
        select(KassaReviewLimit)
        .order_by(KassaReviewLimit.provider)
        .execution_options(populate_existing=True)
    )
    rows = list((await db.execute(stmt)).scalars())
    newest = max(rows, key=lambda r: r.updated_at, default=None)
    author = None
    if newest is not None and newest.updated_by is not None:
        user = await db.get(User, newest.updated_by)
        if user is not None:
            author = AuthorOut(id=user.id, display_name=user.display_name)
    return ReviewLimitsOut(
        limits=[
            KassaLimitOut(
                provider=r.provider,
                enabled=r.enabled,
                max_amount_uzs=wire_uzs(r.max_amount_uzs),
                window_hours=r.window_hours,
            )
            for r in rows
        ],
        updated_at=newest.updated_at if newest else None,
        updated_by=author,
    )


def _stale(at: datetime | None, expected: str) -> bool:
    """Whether the limits moved since ``expected`` (an ``updated_at`` or ``none``)."""
    seen = expected.strip().strip('"')
    if seen.lower() == "none":
        return at is not None
    try:
        return at is None or at != datetime.fromisoformat(seen)
    except ValueError as exc:
        raise ValidationError("If-Match is not a version", code="if_match") from exc


def _plain(row: KassaReviewLimit | None) -> dict[str, object]:
    if row is None:
        return {}
    return {
        "enabled": row.enabled,
        "max_amount_uzs": wire_uzs(row.max_amount_uzs),
        "window_hours": row.window_hours,
    }


async def save_limits(
    db: AsyncSession, *, body: ReviewLimitsIn, admin_id: str, expected: str | None
) -> None:
    """Upsert the given kassas' limits; refuse a stale tab; audit the changed fields.

    Flushes, never commits.

    Raises:
        ConflictError: ``settings_stale`` — ``expected`` is not the saved version.
    """
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext("risk:kassa_limits"))))
    if expected is not None and _stale(await _version(db), expected):
        raise ConflictError("the limits were saved by someone else", code="settings_stale")
    diff: AuditPayload = {}
    stamp = now()
    for item in body.limits:
        row = await db.get(
            KassaReviewLimit, item.provider, with_for_update=True, populate_existing=True
        )
        before = _plain(row)
        if row is None:
            row = KassaReviewLimit(provider=item.provider)
            db.add(row)
        row.enabled = item.enabled
        row.max_amount_uzs = Decimal(item.max_amount_uzs)
        row.window_hours = item.window_hours
        row.updated_by = admin_id
        row.updated_at = stamp
        for field, value in _plain(row).items():
            if before.get(field) != value:
                old, new = json.dumps(before.get(field)), json.dumps(value)
                diff[f"{item.provider}.{field}"] = f"{old} -> {new}".replace('"', "")
    await db.flush()
    await record(
        db,
        actor_id=admin_id,
        action="payments.review_limits.update",
        target_type="kassa_review_limits",
        target_id="all",
        payload=diff or {"unchanged": "true"},
    )
