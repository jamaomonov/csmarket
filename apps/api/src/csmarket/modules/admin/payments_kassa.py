"""The kassas' own transactions behind one payment, reduced for an operator.

Each acquirer keeps its own table keyed by ``payment_id``; this module reads the three and
renders them as :class:`KassaTxnOut`. ``extra`` is an allow-list of scalar fields: nothing
else of a kassa's row (Payme fiscal receipts, Uzum's whole ``payment_source``) is passed
through, and the payer's phone — which Uzum stores in ``payment_source`` — leaves only masked.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.money import wire_uzs
from csmarket.modules.admin.payments_schemas import KassaTimes, KassaTxnOut
from csmarket.modules.click.api import ClickTransaction
from csmarket.modules.payme.api import PaymeTransaction
from csmarket.modules.uzum.api import UzumTransaction

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MASK = "••••••"
_PAYME_STATES = {1: "created", 2: "performed", -1: "cancelled", -2: "cancelled_after_perform"}
#: ``paymentSource`` is a short label ("UZCARD", "HUMO"); anything longer is cut.
_SOURCE_MAX = 32


def _ms(value: int | None) -> datetime | None:
    """Epoch milliseconds as a UTC datetime; ``0`` and ``None`` mean "not set"."""
    return _EPOCH + timedelta(milliseconds=value) if value else None


def mask_phone(value: Any) -> str | None:  # Any: a JSON value from a kassa body
    """A payer's phone with all but its last two digits hidden; ``None`` when there is none.

    A Uzbek number (``998`` + 9 digits) keeps its ``+998``; a value of four digits or fewer is
    hidden whole, so a short string never gives itself away.

    Examples:
        >>> mask_phone("998901234567")
        '+998••••••67'
        >>> mask_phone("90 123-45-67")
        '••••••67'
    """
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    if len(digits) <= 4:
        return _MASK
    prefix = "+998" if len(digits) == 12 and digits.startswith("998") else ""
    return f"{prefix}{_MASK}{digits[-2:]}"


def _click(txn: ClickTransaction) -> KassaTxnOut:
    extra = {"account": txn.account, "service_id": str(txn.service_id)}
    if txn.click_paydoc_id is not None:
        extra["click_paydoc_id"] = str(txn.click_paydoc_id)
    return KassaTxnOut(
        provider="click",
        external_id=str(txn.click_trans_id),
        status=txn.status,
        amount=wire_uzs(txn.amount),
        amount_unit="soum",
        times=KassaTimes(
            created=txn.prepare_time or txn.created_at,
            performed=txn.complete_time,
            cancelled=txn.cancel_time,
        ),
        extra=dict(sorted(extra.items())),
    )


def _payme(txn: PaymeTransaction) -> KassaTxnOut:
    extra = {"account": txn.account}
    if txn.reason is not None:
        extra["reason"] = str(txn.reason)
    return KassaTxnOut(
        provider="payme",
        external_id=txn.payme_id,
        status=_PAYME_STATES.get(txn.state, str(txn.state)),
        amount=str(txn.amount_tiyin),
        amount_unit="tiyin",
        times=KassaTimes(
            created=_ms(txn.create_time) or txn.created_at,
            performed=_ms(txn.perform_time),
            cancelled=_ms(txn.cancel_time),
        ),
        extra=extra,
    )


def _uzum(txn: UzumTransaction) -> KassaTxnOut:
    extra = {"account": txn.account}
    if txn.service_id is not None:
        extra["service_id"] = str(txn.service_id)
    source = txn.payment_source.get("paymentSource")
    if isinstance(source, str) and source:
        extra["source"] = source[:_SOURCE_MAX]
    if (phone := mask_phone(txn.payment_source.get("phone"))) is not None:
        extra["phone"] = phone
    return KassaTxnOut(
        provider="uzum",
        external_id=txn.trans_id,
        status=txn.status,
        amount=str(txn.amount_tiyin),
        amount_unit="tiyin",
        times=KassaTimes(
            created=_ms(txn.create_time) or txn.created_at,
            performed=_ms(txn.confirm_time),
            cancelled=_ms(txn.reverse_time),
        ),
        extra=extra,
    )


async def kassa_transactions(db: AsyncSession, payment_id: str) -> list[KassaTxnOut]:
    """Every Click, Payme and Uzum row of this payment, oldest first."""
    click = await db.scalars(
        select(ClickTransaction).where(ClickTransaction.payment_id == payment_id)
    )
    payme = await db.scalars(
        select(PaymeTransaction).where(PaymeTransaction.payment_id == payment_id)
    )
    uzum = await db.scalars(select(UzumTransaction).where(UzumTransaction.payment_id == payment_id))
    rows = [*map(_click, click), *map(_payme, payme), *map(_uzum, uzum)]
    rows.sort(key=lambda r: (r.times.created or _EPOCH, r.provider, r.external_id))
    return rows


__all__ = ["kassa_transactions", "mask_phone"]
