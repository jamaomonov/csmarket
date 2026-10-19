"""The kassa fee the buyer pays on top (spec 2026-10-14-kassa-fee).

Row 1 of ``payment_settings`` holds a percent per kassa. :func:`kassa_charge` is the one place
that says what a kassa must charge for a payable: the base plus the fee frozen on the live
attempt or, before any attempt exists, the current rate (``hooks.ensure_attempt`` then freezes
it). No cache: one primary-key read per kassa call is cheaper than keeping a copy honest. A row
that no longer parses reads as no fees, with a warning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.payments.fsm import LIVE
from csmarket.modules.payments.models import Payment, PaymentSettingsRow
from csmarket.modules.payments.payable import Payable

log = get_logger("csmarket.payments.fees")


KassaStatus = Literal["on", "maintenance", "off"]
#: Kassas that start switched off until the owner turns them on (spec 2026-10-19-p2p-topup).
_OFF_BY_DEFAULT = frozenset({"p2p"})


class KassaFees(BaseModel):
    """The whole document, as stored in ``payment_settings.settings``: percent per kassa and
    each kassa's switch."""

    model_config = ConfigDict(frozen=True)

    click: Decimal = Field(default=Decimal(0), ge=0, le=10, max_digits=4, decimal_places=2)
    payme: Decimal = Field(default=Decimal(0), ge=0, le=10, max_digits=4, decimal_places=2)
    uzum: Decimal = Field(default=Decimal(0), ge=0, le=10, max_digits=4, decimal_places=2)

    #: A kassa's switch; a missing key is ``on`` (``off`` for :data:`_OFF_BY_DEFAULT`).
    statuses: dict[str, KassaStatus] = Field(default_factory=dict)

    def status(self, provider: str) -> KassaStatus:
        """``provider``'s switch: ``on``, ``maintenance`` (shown, not payable) or ``off``."""
        default: KassaStatus = "off" if provider in _OFF_BY_DEFAULT else "on"
        return self.statuses.get(provider, default)

    def pct(self, provider: str) -> Decimal:
        """The percent of ``provider``; 0 for the balance, ``mock`` and anything else."""
        rates = {"click": self.click, "payme": self.payme, "uzum": self.uzum}
        return rates.get(provider, Decimal(0))


DEFAULT_KASSA_FEES = KassaFees()


def fee_of(base: Decimal, pct: Decimal) -> Decimal:
    """``ceil(base × pct / 100)`` whole soʻm."""
    return (base * pct / 100).to_integral_value(rounding=ROUND_CEILING)


def plain_pct(pct: Decimal) -> str:
    """A percent as the shortest digits: ``1.50`` → ``"1.5"``, ``0.00`` → ``"0"``."""
    return format(pct.normalize(), "f")


@dataclass(frozen=True)
class Charge:
    """What a kassa takes for a payable: the percent, the fee and base + fee, whole soʻm."""

    pct: Decimal
    fee_uzs: Decimal
    total_uzs: Decimal


async def settings_row(db: AsyncSession) -> PaymentSettingsRow | None:
    """Row 1, read fresh."""
    return await db.get(PaymentSettingsRow, 1, populate_existing=True)


async def read_kassa_fees(db: AsyncSession) -> KassaFees:
    """The saved document, or no fees at all."""
    row = await settings_row(db)
    if row is None:
        return DEFAULT_KASSA_FEES
    try:
        return KassaFees.model_validate(row.settings)
    except ValidationError:
        log.warning("payments.fees.row_invalid", reason="falling back to no fees")
        return DEFAULT_KASSA_FEES


async def save_kassa_fees(db: AsyncSession, *, fees: KassaFees, admin_id: str) -> None:
    """Upsert row 1; flushes, never commits. Open attempts keep their frozen fee."""
    document = json.loads(fees.model_dump_json())
    row = await settings_row(db)
    if row is None:
        db.add(PaymentSettingsRow(id=1, settings=document, updated_by=admin_id))
    else:
        row.settings, row.updated_by, row.updated_at = document, admin_id, now()
    await db.flush()


async def current_charge(db: AsyncSession, *, base: Decimal, provider: str) -> Charge:
    """The charge on ``base`` at today's rate of ``provider`` — for a new attempt."""
    pct = (await read_kassa_fees(db)).pct(provider)
    fee = fee_of(base, pct)
    return Charge(pct=pct, fee_uzs=fee, total_uzs=base + fee)


async def kassa_charge(db: AsyncSession, payable: Payable, provider: str) -> Charge:
    """What ``provider`` must charge for ``payable``: its live attempt's frozen fee, else today's.

    A ``not_found`` payable has a base of 0 and so no fee (the caller refuses it anyway).
    """
    if payable.order is not None:
        owned = Payment.order_id == payable.order.id
    elif payable.topup is not None:
        owned = Payment.topup_id == payable.topup.id
    else:
        return Charge(pct=Decimal(0), fee_uzs=Decimal(0), total_uzs=payable.amount_uzs)
    live = (
        await db.execute(
            select(Payment)
            .where(owned, Payment.provider == provider, Payment.status.in_(LIVE))
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if live is not None:
        total = live.amount_uzs + live.fee_uzs
        return Charge(pct=live.fee_pct, fee_uzs=live.fee_uzs, total_uzs=total)
    return await current_charge(db, base=payable.amount_uzs, provider=provider)


__all__ = [
    "DEFAULT_KASSA_FEES",
    "Charge",
    "KassaFees",
    "current_charge",
    "fee_of",
    "kassa_charge",
    "plain_pct",
    "read_kassa_fees",
    "save_kassa_fees",
    "settings_row",
]
