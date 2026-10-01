"""Wire shapes for ``/api/v1/admin/payments`` (the admin SPA's payments pages).

Amounts are digit strings: whole soʻm for ours and for Click, **tiyin** for Payme and Uzum
(``KassaTxnOut.amount_unit`` says which). A kassa's own fields reach the operator only through
``extra``, a flat string map built from an allow-list: no credential, no fiscal receipt and
no full phone number ever leaves (Uzum's ``payment_source`` is reduced to a source name and a
masked phone).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Provider = Literal["click", "payme", "uzum", "mock"]
PaymentStatus = Literal["created", "pending", "succeeded", "failed", "cancelled", "refunded"]
Purpose = Literal["topup", "order"]


class AdminPaymentUser(BaseModel):
    """Who the payment belongs to."""

    id: str
    display_name: str | None


class AdminPaymentRow(BaseModel):
    """One payment attempt in the list."""

    id: str
    #: The payable's public number (a top-up's ``T…``).
    number: str
    purpose: Purpose
    provider: str
    #: Whole soʻm, digits.
    amount_uzs: str
    status: PaymentStatus
    created_at: datetime
    succeeded_at: datetime | None
    user: AdminPaymentUser


class AdminPaymentsOut(BaseModel):
    """A page of payments, newest first, and the cursor for the next (``null`` on the last)."""

    items: list[AdminPaymentRow]
    next_cursor: str | None


class AdminPaymentFull(AdminPaymentRow):
    """The list row plus our reference at the kassa and the attempt's scalar metadata."""

    provider_ref: str | None
    #: Kassa event ids (``settle_event_id``, ``reverse_event_id``); scalar values only.
    metadata: dict[str, str | int | bool | None]


class AdminTopupInfo(BaseModel):
    """The top-up the payment pays for."""

    number: str
    amount_uzs: str
    status: Literal["pending", "succeeded", "expired", "reversed"]
    expires_at: datetime
    succeeded_at: datetime | None


class KassaTimes(BaseModel):
    """When the kassa created, performed and cancelled the transaction (``null`` = not yet)."""

    created: datetime | None
    performed: datetime | None
    cancelled: datetime | None


class KassaTxnOut(BaseModel):
    """One transaction the kassa holds for this payment."""

    provider: Literal["click", "payme", "uzum"]
    #: Click ``click_trans_id``, Payme ``payme_id``, Uzum ``trans_id``.
    external_id: str
    #: Click ``PREPARED``/``CONFIRMED``/``CANCELLED``; Payme ``created``/``performed``/
    #: ``cancelled``/``cancelled_after_perform``; Uzum ``CREATED``/``CONFIRMED``/``REVERSED``/
    #: ``FAILED``.
    status: str
    #: Digits in ``amount_unit``.
    amount: str
    amount_unit: Literal["soum", "tiyin"]
    times: KassaTimes
    #: Allow-listed scalars for the operator, e.g. ``account``, ``click_paydoc_id``,
    #: ``reason``, ``service_id``, and for Uzum ``source`` and a masked ``phone``.
    extra: dict[str, str]


class AdminPaymentDetail(BaseModel):
    """A payment with its top-up and the kassas' transactions."""

    payment: AdminPaymentFull
    topup: AdminTopupInfo | None
    kassa: list[KassaTxnOut]


__all__ = [
    "AdminPaymentDetail",
    "AdminPaymentFull",
    "AdminPaymentRow",
    "AdminPaymentUser",
    "AdminPaymentsOut",
    "AdminTopupInfo",
    "KassaTimes",
    "KassaTxnOut",
    "PaymentStatus",
    "Provider",
    "Purpose",
]
