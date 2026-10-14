"""«Настройки оплаты»: the admin's read and audited save of the kassa fees
(spec 2026-10-14-kassa-fee). Shaped like the sale settings: row 1, ``If-Match`` against a stale
tab, the changed fields in the audit."""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, ValidationError
from csmarket.modules.admin.api import AuditPayload, record
from csmarket.modules.payments.fees import KassaFees, read_kassa_fees, save_kassa_fees
from csmarket.modules.payments.models import PaymentSettingsRow
from csmarket.modules.users.api import User


class SettingsAuthorOut(BaseModel):
    """Who saved the settings."""

    id: str
    display_name: str | None


class PaymentSettingsOut(BaseModel):
    """The kassa fees, who saved them and when (``null`` before the first save)."""

    settings: KassaFees
    updated_at: datetime | None
    updated_by: SettingsAuthorOut | None


async def settings_view(db: AsyncSession) -> PaymentSettingsOut:
    """The document as the admin page shows it."""
    row = await db.get(PaymentSettingsRow, 1, populate_existing=True)
    author: SettingsAuthorOut | None = None
    if row is not None and row.updated_by is not None:
        name = await db.scalar(select(User.display_name).where(User.id == row.updated_by))
        author = SettingsAuthorOut(id=row.updated_by, display_name=name)
    return PaymentSettingsOut(
        settings=await read_kassa_fees(db),
        updated_at=row.updated_at if row is not None else None,
        updated_by=author,
    )


def _stale(row_at: datetime | None, expected: str) -> bool:
    """Whether the row moved since ``expected`` (an ``updated_at`` or ``none``)."""
    seen = expected.strip().strip('"')
    if seen.lower() == "none":
        return row_at is not None
    try:
        at = datetime.fromisoformat(seen)
    except ValueError as exc:
        raise ValidationError("If-Match is not a version", code="if_match") from exc
    return row_at is None or row_at != at


def _diff(before: KassaFees, after: KassaFees) -> AuditPayload:
    """Every changed rate as ``"<old> -> <new>"`` (an audit payload is flat)."""
    old, new = before.model_dump(mode="json"), after.model_dump(mode="json")
    changed: AuditPayload = {
        k: f"{json.dumps(old[k])} -> {json.dumps(v)}" for k, v in new.items() if old[k] != v
    }
    return changed or {"unchanged": "true"}


async def save_settings(
    db: AsyncSession, *, fees: KassaFees, admin_id: str, expected: str | None = None
) -> None:
    """Replace the document; audited ``payments.settings.save``. Flushes, never commits.

    Raises:
        ConflictError: ``settings_stale`` — ``expected`` is not the saved version.
    """
    row = await db.get(PaymentSettingsRow, 1, with_for_update=True, populate_existing=True)
    if expected is not None and _stale(row.updated_at if row else None, expected):
        raise ConflictError("the settings were saved by someone else", code="settings_stale")
    before = await read_kassa_fees(db)
    await save_kassa_fees(db, fees=fees, admin_id=admin_id)
    await record(
        db,
        actor_id=admin_id,
        action="payments.settings.save",
        target_type="payment_settings",
        target_id="1",
        payload=_diff(before, fees),
    )


__all__ = ["PaymentSettingsOut", "SettingsAuthorOut", "save_settings", "settings_view"]
