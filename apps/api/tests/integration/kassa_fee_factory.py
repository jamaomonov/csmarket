"""Save the kassa fees the way the admin does (spec 2026-10-14-kassa-fee)."""

from __future__ import annotations

from decimal import Decimal

from csmarket.modules.payments.fees import KassaFees, save_kassa_fees
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user


async def set_fees(db: AsyncSession, *, statuses: dict[str, str] | None = None, **pct: str) -> None:
    """Commit row 1 with the given percents (others 0) and kassa switches, saved by a fresh
    user."""
    admin = await make_user(db)
    fees = KassaFees.model_validate(
        {**{k: Decimal(v) for k, v in pct.items()}, "statuses": statuses or {}}
    )
    await save_kassa_fees(db, fees=fees, admin_id=admin.id)
    await db.commit()
