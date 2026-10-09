"""An admin refunds a Skinslink or LIS-SKINS order, after the source confirms the purchase
did not happen (plan C Task 5, ADR-0018).

The Waxpeer admin refund's shape (``admin_actions.admin_refund``, ADR-0007): an unlocked read
refuses early (:func:`purchase_refund_refusal`) and ends the transaction; the source is asked
once (:data:`REFUND_LOOKUP_SECONDS`) with no lock and
no transaction open; then the order and its purchase are locked, the refusal is checked again,
``buy_pending`` is turned off and ``refund_to_balance`` books the refund (soʻm, or the USD
wallet of an API order).

What the source must say:

========================  ==========================================================
Skinslink ``failed`` /    refundable — nothing will reach the buyer
``canceled``
LIS-SKINS skin ``return`` refundable — unless a ``rollback_…`` reason (the skin was
                          accepted, then undone: it may be spent)
not found                 refundable only for a row with no market purchase id on
                          record and no lost buy answer (``buy_unconfirmed_at`` —
                          a silence is never refunded), older than
                          :data:`UNSEEN_AFTER`, no buy running (the refusal checks
                          those before asking)
someone else's answer     ``order_in_flight``: a Skinslink report under another
                          ``merchant_tx_id`` or purchase id, a LIS-SKINS answer with
                          entries but none ours, an unreadable entry, another
                          purchase id
anything else             ``order_in_flight`` (``active``, ``hold``, ``completed``,
                          ``reverted``, ``accepted``, ``wait_accept``, …)
a failed lookup           ``source_unavailable``
========================  ==========================================================

The detail's ``can_refund`` (:func:`purchase_can_refund`) also hides the button while the
purchase status we stored is plainly live; the source's answer stays the authority.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import NotFoundError
from csmarket.core.logging import get_logger
from csmarket.core.numbers import is_number, is_topup_number
from csmarket.modules.lisskins.api import InfoAnswer, LisskinsError, LisskinsUnavailableError
from csmarket.modules.orders.admin_conflicts import REFUND_LOOKUP_SECONDS, conflict
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.purchase_rows import PurchaseRow, purchase_of
from csmarket.modules.orders.refunds import BLOCKS_REFUND, RefundStatus, refund_to_balance
from csmarket.modules.skinslink.api import Purchase as SkinslinkReport
from csmarket.modules.skinslink.api import (
    SkinslinkError,
    SkinslinkPurchase,
    SkinslinkUnavailableError,
)

log = get_logger("csmarket.orders.admin")

#: The order statuses whose purchase an admin may undo here (the skin is not delivered).
REFUNDABLE_STATUSES: frozenset[str] = frozenset({"buying", "trade_sent"})
#: How old a purchase row with no market purchase id must be before «not found» means
#: «never bought».
UNSEEN_AFTER = timedelta(minutes=10)
#: Skinslink statuses that undo the purchase before it reached the buyer.
SKINSLINK_UNDONE: frozenset[str] = frozenset({"failed", "canceled"})
#: Stored statuses under which the skin is on its way or delivered: no refund button.
STORED_LIVE: dict[str, frozenset[str]] = {
    "skinslink": frozenset({"active", "hold", "completed"}),
    "lisskins": frozenset({"accepted", "wait_accept", "wait_unlock", "wait_withdraw"}),
}
#: A failed lookup refuses the refund (``source_unavailable``).
LOOKUP_ERRORS = (
    SkinslinkError,
    SkinslinkUnavailableError,
    LisskinsError,
    LisskinsUnavailableError,
    TimeoutError,
)


class SkinslinkStatusClient(Protocol):
    """What the refund needs from Skinslink."""

    async def purchase_status(self, *, merchant_tx_id: str) -> SkinslinkReport | None:
        """The purchase under ``merchant_tx_id``, or ``None`` when Skinslink has none."""
        ...


class LisskinsInfoClient(Protocol):
    """What the refund needs from LIS-SKINS."""

    async def info_answer(self, *, custom_ids: Sequence[str]) -> InfoAnswer:
        """The purchases under ``custom_ids`` (an unknown id is absent) and the number of
        entries the answer held, unreadable ones included."""
        ...


@dataclass(frozen=True)
class _Seen:
    """What the unlocked read saw: the lookup key and the market purchase id on record then."""

    order_id: str
    source: str
    key: str
    purchase_id: int | None
    unconfirmed_at: datetime | None

    @property
    def unseen_refundable(self) -> bool:
        """«Not found» means «never bought»: no purchase id on record, no lost buy answer."""
        return self.purchase_id is None and self.unconfirmed_at is None


def purchase_buy_running(order: Order, purchase: PurchaseRow, at: datetime) -> bool:
    """An attempt may hold the order's buy lease: ``buy_pending`` and ``next_check_at > at``."""
    return purchase.buy_pending and order.next_check_at is not None and order.next_check_at > at


def purchase_refund_refusal(order: Order, purchase: PurchaseRow | None, at: datetime) -> str | None:
    """Why an admin may not refund a Skinslink / LIS-SKINS ``order`` now (a 409 code), or
    ``None`` when the source should be asked. No source call: the detail's ``can_refund``.

    ``already_refunded``; ``order_not_refundable`` unless ``buying`` / ``trade_sent``, paid,
    with a purchase row; ``order_needs_attention`` while an attention that blocks refunds
    (R3) is unresolved; ``order_busy`` while a buy attempt holds the lease;
    ``order_in_flight`` for a row younger than :data:`UNSEEN_AFTER` with no market purchase
    id (its buy may not be visible at the source yet).
    """
    if order.refunded_at is not None:
        return "already_refunded"
    if order.status not in REFUNDABLE_STATUSES or order.paid_with is None or purchase is None:
        return "order_not_refundable"
    if purchase.attention_reason in BLOCKS_REFUND and purchase.resolved_at is None:
        return "order_needs_attention"
    if purchase_buy_running(order, purchase, at):
        return "order_busy"
    if purchase.purchase_id is None and at - purchase.created_at < UNSEEN_AFTER:
        return "order_in_flight"
    return None


def purchase_can_refund(order: Order, purchase: PurchaseRow | None, at: datetime) -> bool:
    """The detail's ``can_refund``: no refusal, and the stored purchase status is not plainly
    live (the button and the action agree; the source's answer still decides)."""
    if purchase_refund_refusal(order, purchase, at) is not None or purchase is None:
        return False
    return purchase.status not in STORED_LIVE.get(order.source, frozenset())


def _key(purchase: PurchaseRow) -> str:
    """The id the source knows our purchase by."""
    if isinstance(purchase, SkinslinkPurchase):
        return purchase.merchant_tx_id
    return purchase.custom_id


async def _read(db: AsyncSession, number: str) -> _Seen:
    """Order ``number`` and its purchase, unlocked, refused early; the read transaction is
    ended either way (nothing is held while the source answers).

    Raises:
        NotFoundError: malformed, a top-up's, or unknown.
        ConflictError: the refusal's code.
    """
    if not is_number(number) or is_topup_number(number):
        raise NotFoundError("order not found")
    order = await db.scalar(
        select(Order).where(Order.number == number).execution_options(populate_existing=True)
    )
    purchase = None if order is None else await purchase_of(db, order, lock=False)
    code = None if order is None else purchase_refund_refusal(order, purchase, now())
    seen = (
        None
        if order is None or purchase is None
        else _Seen(
            order.id,
            order.source,
            _key(purchase),
            purchase.purchase_id,
            purchase.buy_unconfirmed_at,
        )
    )
    await db.commit()  # nothing written: the read transaction ends before the source is asked
    if order is None:
        raise NotFoundError("order not found")
    if code is not None or seen is None:
        raise conflict(code or "order_not_refundable")
    return seen


def _skinslink_verdict(report: SkinslinkReport | None, seen: _Seen) -> str | None:
    if report is None:
        return None if seen.unseen_refundable else "order_in_flight"
    if report.merchant_tx_id != seen.key:
        return "order_in_flight"  # not an answer about our purchase
    if seen.purchase_id is not None and report.id != seen.purchase_id:
        return "order_in_flight"
    return None if report.status in SKINSLINK_UNDONE else "order_in_flight"


def _lisskins_verdict(answer: InfoAnswer, seen: _Seen) -> str | None:
    if answer.entries != len(answer.purchases):
        return "order_in_flight"  # an unreadable entry may be ours
    mine = [p for p in answer.purchases if p.custom_id == seen.key]
    if not mine:
        if answer.entries or not seen.unseen_refundable:
            return "order_in_flight"
        return None
    if seen.purchase_id is not None and any(p.purchase_id != seen.purchase_id for p in mine):
        return "order_in_flight"
    skins = [s for p in mine for s in p.skins]
    returned = all(
        s.status == "return" and not (s.return_reason or "").startswith("rollback_") for s in skins
    )
    return None if skins and returned else "order_in_flight"


async def _ask(
    seen: _Seen,
    *,
    number: str,
    skinslink: SkinslinkStatusClient,
    lisskins: LisskinsInfoClient,
) -> None:
    """Refuse the refund unless the source confirms the purchase did not happen.

    Raises:
        ConflictError: ``order_in_flight``; ``source_unavailable`` — the lookup failed or
            timed out.
    """
    try:
        async with asyncio.timeout(REFUND_LOOKUP_SECONDS):
            if seen.source == "skinslink":
                report = await skinslink.purchase_status(merchant_tx_id=seen.key)
                code = _skinslink_verdict(report, seen)
            else:
                code = _lisskins_verdict(await lisskins.info_answer(custom_ids=[seen.key]), seen)
    except LOOKUP_ERRORS as exc:
        log.warning(
            "orders.admin_refund.lookup_failed",
            number=number,
            source=seen.source,
            error=type(exc).__name__,
        )
        raise conflict("source_unavailable") from None
    if code is not None:
        log.warning("orders.admin_refund.purchase_seen", number=number, source=seen.source)
        raise conflict(code)


async def _lock(db: AsyncSession, order_id: str) -> tuple[Order, PurchaseRow | None]:
    """The order, then its purchase, ``FOR UPDATE`` (ruling K), read fresh."""
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:  # pragma: no cover - orders are never deleted under a refund
        raise NotFoundError("order not found")
    return order, await purchase_of(db, order, lock=True)


async def admin_refund_purchase(
    db: AsyncSession,
    *,
    number: str,
    admin_id: str,
    skinslink: SkinslinkStatusClient,
    lisskins: LisskinsInfoClient,
) -> Order:
    """An admin refunds Skinslink / LIS-SKINS order ``number`` (reason ``admin``): a
    ``buying`` order becomes ``failed``, a ``trade_sent`` one ``returned``.

    Read unlocked and refuse early, end the transaction, ask the source once (4 s, nothing
    locked), lock the order then its purchase, check again — a purchase id or a lost buy answer
    recorded meanwhile means the answer no longer covers the row (``order_in_flight``) — turn ``buy_pending`` off
    and book the refund. Flushes, never commits; returns with the locks held.

    Args:
        db: Session; the order and its purchase are locked here.
        number: The order's public number.
        admin_id: The admin's user id (booked as actor ``admin:<id>``, never logged).
        skinslink: Skinslink, for a Skinslink order's lookup.
        lisskins: LIS-SKINS, for a LIS-SKINS order's lookup.

    Returns:
        The refunded order.

    Raises:
        NotFoundError: no such order.
        ConflictError: a :func:`purchase_refund_refusal` code; ``order_in_flight`` — the
            source shows a purchase that may reach the buyer; ``source_unavailable``.
    """
    seen = await _read(db, number)
    await _ask(seen, number=number, skinslink=skinslink, lisskins=lisskins)
    order, purchase = await _lock(db, seen.order_id)
    at = now()
    code = purchase_refund_refusal(order, purchase, at)
    moved = purchase is None or (purchase.purchase_id, purchase.buy_unconfirmed_at) != (
        seen.purchase_id,
        seen.unconfirmed_at,
    )
    if code is None and moved:  # the answer no longer covers the row
        code = "order_in_flight"
    if code is not None or purchase is None:
        raise conflict(code or "order_not_refundable")
    purchase.buy_pending = False
    purchase.updated_at = at
    await db.flush()
    # A sent offer that died comes back as ``returned`` (the FSM has no trade_sent → failed).
    to: RefundStatus = "returned" if order.status == "trade_sent" else "failed"
    await refund_to_balance(
        db, order=order, to_status=to, reason="admin", actor=f"admin:{admin_id}"
    )
    return order


__all__ = [
    "REFUNDABLE_STATUSES",
    "REFUND_LOOKUP_SECONDS",
    "SKINSLINK_UNDONE",
    "STORED_LIVE",
    "UNSEEN_AFTER",
    "LisskinsInfoClient",
    "SkinslinkStatusClient",
    "admin_refund_purchase",
    "purchase_buy_running",
    "purchase_can_refund",
    "purchase_refund_refusal",
]
