"""A deposit's status, applied to its sale (spec 2026-10-08 §6).

:func:`apply_deposit` is the one place a sale moves. It runs under the sale's row lock
(:func:`lock_sale`), flushes and never commits. :func:`check_sale` reads the sale, ends the
transaction, asks Skinslink ``deposit/status`` and applies the answer under the lock — the
worker (a webhook's check), the poll and ``POST /sell`` all go through it or through
:func:`apply_deposit`, so a webhook body is never trusted and no call holds a lock.

- ``creating`` + ``active`` → ``offered`` (``new`` / ``pending`` only record the poll; never
  back from ``hold``);
- + ``hold`` → ``hold``, ``hold_end_at`` kept; a card sale's request opens ``waiting_hold``;
- + ``completed`` → ``credited`` (balance: the ledger credit, keyed by the sale, so at most
  once) or ``payout`` (card: the request becomes ``to_pay``);
- + ``failed`` / ``canceled`` → ``closed``; + ``reverted`` → ``reverted``; an open request is
  canceled — nothing was paid;
- ``creating`` that Skinslink does not know after :data:`NOT_FOUND_GRACE` → ``closed``
  (``not_created``: the call never landed);
- settled: ``reverted`` after the money left → ``attention_reason = rolled_back``, no debit
  (a ``payout`` whose request is still ``to_pay`` is reverted instead: nothing was paid); a
  ``closed`` sale Skinslink reports alive or reverted → ``late_deposit`` (nothing was paid).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import record_sale_outcome
from csmarket.modules.realtime.api import nudge_sale
from csmarket.modules.sales.letters import enqueue_sale_letter
from csmarket.modules.sales.models import OPEN_STATUSES, Sale
from csmarket.modules.sales.payouts import cancel_request, open_request, request_of
from csmarket.modules.skinslink.api import (
    Deposit,
    DepositClient,
    SkinslinkError,
    SkinslinkUnavailableError,
)
from csmarket.modules.wallet.api import credit_sale

log = get_logger("csmarket.sales.status")

Outcome = Literal[
    "unchanged", "offered", "hold", "credited", "payout", "closed", "reverted", "attention"
]
#: How long a ``creating`` sale Skinslink does not know stays open (the call may be in flight).
NOT_FOUND_GRACE = timedelta(minutes=2)
_LIVE = frozenset({"new", "pending", "active"})
_DEAD = frozenset({"failed", "canceled"})
_USD = Decimal("0.000001")


async def lock_sale(db: AsyncSession, sale_id: str) -> Sale | None:
    """Sale ``sale_id`` ``FOR UPDATE``, read fresh."""
    return await db.scalar(
        select(Sale)
        .where(Sale.id == sale_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _parse_at(value: str | None) -> datetime | None:
    """An ISO 8601 time from Skinslink, as an aware UTC datetime; ``None`` if unreadable."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _record(sale: Sale, report: Deposit) -> None:
    """Keep what Skinslink says about the offer; a missing field never erases a known one."""
    sale.trade_id = report.id
    if report.trade_offer_id:
        sale.trade_offer_id = report.trade_offer_id[:32]
    if report.bot_name:
        sale.bot_name = report.bot_name[:64]
    sale.offer_expiry_at = _parse_at(report.offer_expiry_at) or sale.offer_expiry_at
    sale.hold_end_at = _parse_at(report.hold_end_date) or sale.hold_end_at
    if report.amount_usd is not None:
        sale.amount_usd = report.amount_usd.quantize(_USD)


async def apply_deposit(
    db: AsyncSession, sale: Sale, report: Deposit | None, *, at: datetime
) -> Outcome:
    """Move ``sale`` by Skinslink's ``report`` (``None``: Skinslink has no such deposit).

    The caller holds ``sale`` ``FOR UPDATE`` and commits. A move enqueues its letter, counts
    the outcome and nudges the seller's socket in the same transaction.
    """
    if report is None:
        outcome = await _missing(db, sale, at)
    else:
        _record(sale, report)
        if sale.status in OPEN_STATUSES:
            outcome = await _open(db, sale, report)
        else:
            outcome = await _settled(db, sale, report.status)
    await _moved(db, sale, outcome)
    return outcome


async def _moved(db: AsyncSession, sale: Sale, outcome: Outcome) -> None:
    """Count a move, nudge the seller's socket and flush; nothing for ``unchanged``."""
    if outcome != "unchanged":
        record_sale_outcome(outcome)
        await nudge_sale(db, user_id=sale.user_id, number=sale.number)
        log.info("sales.moved", number=sale.number, outcome=outcome)
    await db.flush()


async def close(db: AsyncSession, sale: Sale, *, reason: str, letter: bool = False) -> Outcome:
    """Close a ``creating`` sale Skinslink refused (no deposit exists); flushes, never commits.

    The caller holds ``sale`` ``FOR UPDATE``. Any other status is left as it is. A refused
    sale sends no letter by default: the seller was told by the answer to ``POST /sell``.
    """
    if sale.status != "creating":
        return "unchanged"
    outcome = await _close(db, sale, reason, letter=letter)
    await _moved(db, sale, outcome)
    return outcome


async def _missing(db: AsyncSession, sale: Sale, at: datetime) -> Outcome:
    if sale.status == "creating" and at - sale.created_at >= NOT_FOUND_GRACE:
        return await _close(db, sale, "not_created", letter=False)
    return "unchanged"


async def _open(db: AsyncSession, sale: Sale, report: Deposit) -> Outcome:
    status = report.status
    if status in _LIVE:
        return _offered(sale, status)
    if status == "hold":
        return await _hold(db, sale)
    if status == "completed":
        return await _complete(db, sale)
    if status in _DEAD:
        reason = report.fail_reason or status
        return await _close(db, sale, reason, letter=sale.status != "creating")
    if status == "reverted":
        return await _revert(db, sale, report.fail_reason or status)
    return "unchanged"


def _offered(sale: Sale, status: str) -> Outcome:
    """Only ``active`` offers a ``creating`` sale; ``new`` / ``pending`` just record the poll
    (spec §6). ``offered`` stays; ``hold`` never steps back."""
    if sale.status != "creating" or status != "active":
        return "unchanged"
    sale.status = "offered"
    return "offered"


async def _hold(db: AsyncSession, sale: Sale) -> Outcome:
    if sale.status == "hold":
        return "unchanged"
    sale.status = "hold"
    if sale.payout_to == "card":
        await open_request(db, sale, status="waiting_hold")
    await enqueue_sale_letter(db, sale, "sale_hold")
    return "hold"


async def _complete(db: AsyncSession, sale: Sale) -> Outcome:
    at = now()
    if sale.payout_to == "balance":
        await credit_sale(db, user_id=sale.user_id, sale_id=sale.id, amount=sale.payout_uzs)
        sale.status, sale.credited_at = "credited", at
        await enqueue_sale_letter(db, sale, "sale_paid", to="balance")
        return "credited"
    request = await open_request(db, sale, status="to_pay")
    if request.status == "waiting_hold":
        request.status = "to_pay"
    request.to_pay_at = request.to_pay_at or at
    sale.status = "payout"
    return "payout"


async def _close(db: AsyncSession, sale: Sale, reason: str, *, letter: bool) -> Outcome:
    sale.status, sale.fail_reason = "closed", reason[:48]
    await cancel_request(db, sale)
    if letter:
        await enqueue_sale_letter(db, sale, "sale_canceled")
    return "closed"


async def _revert(db: AsyncSession, sale: Sale, reason: str) -> Outcome:
    sale.status, sale.fail_reason = "reverted", reason[:48]
    await cancel_request(db, sale)
    await enqueue_sale_letter(db, sale, "sale_canceled")
    return "reverted"


async def _settled(db: AsyncSession, sale: Sale, status: str) -> Outcome:
    if sale.status == "closed" and status not in _DEAD:  # nothing was paid: not a rollback
        return _attention(sale, "late_deposit")
    if status == "reverted":
        return await _revert_settled(db, sale)
    return "unchanged"


async def _revert_settled(db: AsyncSession, sale: Sale) -> Outcome:
    if sale.status == "reverted":
        return "unchanged"
    if sale.status == "payout":
        request = await request_of(db, sale.id, lock=True)
        if request is not None and request.status == "to_pay":  # nothing was paid yet
            return await _revert(db, sale, "reverted")
    return _attention(sale, "rolled_back")


def _attention(sale: Sale, reason: str) -> Outcome:
    if sale.attention_reason is not None:
        return "unchanged"
    sale.attention_reason = reason
    log.warning("sales.attention", number=sale.number, reason=reason)
    return "attention"


async def check_sale(db: AsyncSession, client: DepositClient, *, sale_id: str) -> Outcome:
    """Ask Skinslink about ``sale_id`` and apply the answer; commits.

    The read transaction ends before the call; the answer is applied under the sale's lock.
    An outage or a refusal changes nothing (the next poll asks again).
    """
    sale = await db.get(Sale, sale_id, populate_existing=True)
    number = sale.number if sale is not None else None
    await db.commit()
    if number is None:
        return "unchanged"
    try:
        report = await client.deposit_status(merchant_tx_id=sale_id)
    except (SkinslinkError, SkinslinkUnavailableError) as exc:
        log.warning("sales.status_unread", number=number, error=type(exc).__name__)
        return "unchanged"
    locked = await lock_sale(db, sale_id)
    if locked is None:
        await db.rollback()
        return "unchanged"
    outcome = await apply_deposit(db, locked, report, at=now())
    locked.last_polled_at = now()
    await db.commit()
    return outcome


__all__ = ["NOT_FOUND_GRACE", "Outcome", "apply_deposit", "check_sale", "close", "lock_sale"]
