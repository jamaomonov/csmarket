"""Kassa switches (spec 2026-10-19-p2p-topup): a new payment only in a kassa that is ``on``.

Payments already opened are never refused here: their callbacks settle whatever the switch
says, or a buyer could be charged and not credited.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError
from csmarket.modules.payments.fees import read_kassa_fees


async def ensure_open(db: AsyncSession, provider: str) -> None:
    """Refuse a new payment in a kassa under maintenance or switched off.

    Raises:
        ConflictError: ``provider_maintenance`` or ``provider_disabled``.
    """
    status = (await read_kassa_fees(db)).status(provider)
    if status == "maintenance":
        raise ConflictError("this kassa is under maintenance", code="provider_maintenance")
    if status == "off":
        raise ConflictError("this kassa is switched off", code="provider_disabled")


__all__ = ["ensure_open"]
