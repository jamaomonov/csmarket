"""A ``provider_ref`` that no earlier attempt of the same provider already holds.

The kassas key an attempt by top-up number (``payme:<number>``). A customer whose card was
declined tries again on the same top-up: the cancelled attempt keeps that reference, and a
new one with the same reference would break ``uq_payments_provider_ref`` — the kassa would
get a system error and show the customer «Сервис поставщика услуг недоступен». The kassa
callbacks find an attempt through their own transaction rows, never by this reference, so
a suffix on a retry is safe.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.payments.models import Payment


async def unclaimed_external_id(
    db: AsyncSession, *, provider: str, external_id: str, payment_id: str
) -> str:
    """``external_id`` for the first attempt, ``<external_id>:<payment_id>`` after.

    Args:
        db: Session.
        provider: The attempt's provider.
        external_id: The reference the attempt would use (``payme:<number>``).
        payment_id: The new attempt's id, for the suffix.
    """
    taken = (
        await db.execute(
            select(Payment.id).where(
                Payment.provider == provider, Payment.provider_ref == external_id
            )
        )
    ).first()
    return external_id if taken is None else f"{external_id}:{payment_id}"


__all__ = ["unclaimed_external_id"]
