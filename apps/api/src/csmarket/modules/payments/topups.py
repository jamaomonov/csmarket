"""Balance top-ups the customer opens (spec §6; owner decision D1; rulings R3, R8, R11).

:func:`create_topup` turns a signed-in customer's request into a ``wallet_topups`` row and
its first attempt in the chosen kassa; the ledger moves only when that kassa (or the dev
``mock``) settles the attempt through :mod:`.hooks`. :func:`expire_stale` closes the
top-ups no kassa ever took up; :func:`dev_pay` drives the real ``settle`` for ``mock``.

Replays: the top-up's own ``(user_id, idempotency_key)`` unique is the source of truth. A
replayed key must name the same request — same amount, same kassa — or it is a 409, both on
the pre-check and on the race path where two requests with one key both missed it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.errors import ConflictError, ValidationError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.core.numbers import allocate, is_topup_number, topup_number
from csmarket.modules.payments.fees import kassa_charge
from csmarket.modules.payments.gateways import PaymentGateway, available_providers, get_gateway
from csmarket.modules.payments.hooks import cancel_pending, ensure_attempt, mark_pending, settle
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import Payable, resolve
from csmarket.modules.payments.switches import ensure_open
from csmarket.modules.wallet.api import WALLET

log = get_logger("csmarket.payments.topups")

#: Attempt statuses that mean a kassa took the top-up up: the sweep leaves it alone (R8).
_HELD = ("pending", "succeeded")


#: The card-transfer kassa (spec 2026-10-19-p2p-topup).
P2P = "p2p"
#: How far a P2P top-up's amount may sit above the typed one (``p2p.card_choice.MAX_BUMP``).
_P2P_MAX_BUMP = 99


@dataclass(frozen=True)
class P2PTransfer:
    """Where and how much to transfer for a P2P top-up."""

    card_number: str
    holder: str
    amount_uzs: int
    expires_at: datetime
    #: The request's own status: ``pending``, ``paid``, ``expired`` or ``cancelled``.
    status: str


@dataclass(frozen=True)
class TopupView:
    """A top-up as its owner sees it: the kassa it was opened in and where to pay."""

    topup: WalletTopup
    #: The kassa of the first attempt (the one the customer chose); ``None`` without one.
    provider: str | None
    #: Where to pay; ``None`` once the top-up cannot be paid (paid, expired, reversed).
    intent_url: str | None
    #: Still ``pending`` while a kassa holds an attempt (Payme state 1, a prepared Click or a
    #: created Uzum transaction): that kassa may still settle it past ``expires_at``.
    awaiting_kassa: bool = False
    #: The kassa fee on top, frozen on the first attempt (spec 2026-10-14-kassa-fee).
    fee_uzs: Decimal = Decimal(0)
    #: A P2P top-up's transfer details (spec 2026-10-19-p2p-topup); ``None`` otherwise.
    p2p: P2PTransfer | None = None


def _check_amount(amount: Decimal) -> None:
    """Owner decision D1: whole soʻm, ``topup_min_uzs`` to ``topup_max_uzs``."""
    s = get_settings()
    whole = amount.is_finite() and amount == amount.to_integral_value()
    if not whole or not s.topup_min_uzs <= amount <= s.topup_max_uzs:
        raise ValidationError(
            "top-up amount out of range",
            code="topup_amount",
            min=s.topup_min_uzs,
            max=s.topup_max_uzs,
        )


def _gateway(provider: str) -> PaymentGateway:
    """The kassa to open the top-up in; the balance itself is never one."""
    gateway = _gateway_or_none(provider)
    if gateway is None:
        raise ValidationError("payment provider not available", code="topup_provider")
    return gateway


def kassa_for_new_topup(provider: str) -> PaymentGateway | None:
    """The kassa a new top-up opens in; ``None`` for P2P (no kassa page: the card and the
    amount come with the top-up).

    Raises:
        ValidationError: ``topup_provider`` — the balance, or a kassa not available here.
    """
    if provider == P2P:
        if P2P not in available_providers():
            raise ValidationError("payment provider not available", code="topup_provider")
        return None
    return _gateway(provider)


def _gateway_or_none(provider: str) -> PaymentGateway | None:
    """``provider``'s gateway while it is available; else ``None`` (also for ``wallet``)."""
    if provider in (WALLET, P2P) or provider not in available_providers():
        return None
    return get_gateway(provider)


async def _intent(
    db: AsyncSession, gateway: PaymentGateway | None, payable: Payable, locale: str
) -> str | None:
    """The kassa page for ``payable``, asking for what the kassa's webhook will check: the base
    plus the live attempt's frozen fee, or today's rate (spec 2026-10-14-kassa-fee)."""
    if gateway is None or not payable.payable:
        return None
    charge = await kassa_charge(db, payable, gateway.provider)
    return gateway.intent_url(payable=payable, charge_uzs=charge.total_uzs, locale=locale)


async def _by_key(db: AsyncSession, *, user_id: str, idempotency_key: str) -> WalletTopup | None:
    stmt = select(WalletTopup).where(
        WalletTopup.user_id == user_id, WalletTopup.idempotency_key == idempotency_key
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _first_attempt(db: AsyncSession, topup_id: str) -> Payment | None:
    """The attempt the top-up was opened with (the customer's chosen kassa)."""
    stmt = (
        select(Payment)
        .where(Payment.topup_id == topup_id)
        .order_by(Payment.created_at, Payment.id)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _assert_replay_matches(
    existing: WalletTopup, first: Payment | None, *, amount: Decimal, provider: str
) -> None:
    """A replayed key must name the same request, or it is not a replay.

    Raises:
        ConflictError: ``idempotency_mismatch`` — the key opened a top-up for another
            amount or another kassa.
    """
    # A P2P top-up holds the typed amount or up to +99 soʻm of it (spec 2026-10-19-p2p-topup).
    bump = existing.amount_uzs - amount
    same_amount = bump == 0 or (provider == P2P and 0 <= bump <= _P2P_MAX_BUMP)
    same = same_amount and (first is None or first.provider == provider)
    if not same:
        raise ConflictError(
            "Idempotency-Key was already used for a different top-up",
            code="idempotency_mismatch",
        )


async def _replay(
    db: AsyncSession,
    existing: WalletTopup,
    *,
    amount: Decimal,
    provider: str,
    locale: str,
) -> tuple[WalletTopup, Payment, str | None]:
    """The stored top-up for a replayed key; no pay URL once its kassa is unavailable."""
    first = await _first_attempt(db, existing.id)
    _assert_replay_matches(existing, first, amount=amount, provider=provider)
    if first is None:  # the top-up and its attempt commit together; never seen
        raise ConflictError("top-up has no payment attempt yet; retry")
    payable = await resolve(db, existing.number)
    return existing, first, await _intent(db, _gateway_or_none(provider), payable, locale)


async def create_topup(
    db: AsyncSession,
    *,
    user_id: str,
    amount_uzs: Decimal,
    provider: str,
    idempotency_key: str,
    locale: str,
) -> tuple[WalletTopup, Payment, str | None]:
    """Open a top-up of ``amount_uzs`` in ``provider``, or replay the one ``idempotency_key`` opened.

    Flushes, never commits. The top-up expires ``topup_expiry_minutes`` from now unless a
    kassa takes it up (R8). A replay is looked up before the kassa is: a replayed key
    returns its stored top-up even after that kassa lost its credentials (then without a
    pay URL).

    Returns:
        The top-up, its first attempt and the URL to pay at (``None`` when a replayed
        top-up can no longer be paid).

    Raises:
        ValidationError: ``topup_amount`` (not a whole soʻm in D1's range) or
            ``topup_provider`` (unknown, unavailable here, or ``wallet``).
        ConflictError: ``idempotency_mismatch`` — the key opened a different top-up.
    """
    existing = await _by_key(db, user_id=user_id, idempotency_key=idempotency_key)
    if existing is not None:
        return await _replay(db, existing, amount=amount_uzs, provider=provider, locale=locale)
    _check_amount(amount_uzs)
    gateway = kassa_for_new_topup(provider)
    await ensure_open(db, provider)
    topup = WalletTopup(
        id=new_id(),
        number=await allocate(db, WalletTopup.number, topup_number),
        user_id=user_id,
        amount_uzs=amount_uzs,
        status="pending",
        idempotency_key=idempotency_key,
        expires_at=now() + timedelta(minutes=get_settings().topup_expiry_minutes),
    )
    try:
        async with db.begin_nested():
            db.add(topup)
            await db.flush()
    except IntegrityError as exc:
        # Two requests with one key both missed the pre-check; the loser lands here once
        # the winner commits. The same comparison as above, not a looser one.
        winner = await _by_key(db, user_id=user_id, idempotency_key=idempotency_key)
        if winner is None:
            raise ConflictError("top-up conflict; retry") from exc
        return await _replay(db, winner, amount=amount_uzs, provider=provider, locale=locale)
    payable = await resolve(db, topup.number, lock=True)
    payment = await ensure_attempt(db, payable=payable, provider=provider)
    if provider == P2P:
        # Late import: ``p2p`` builds on ``payments`` (it settles through its hooks); this is
        # the one call back into it, at request time (spec 2026-10-19-p2p-topup, ADR-0021).
        from csmarket.modules.p2p.api import reserve_topup

        await reserve_topup(db, topup=topup, payment=payment, at=now())
        log.info("payments.topup.created", number=topup.number, provider=provider)
        return topup, payment, None
    log.info(
        "payments.topup.created", number=topup.number, provider=provider, amount=str(amount_uzs)
    )
    return topup, payment, await _intent(db, gateway, payable, locale)


async def credit_received_transfer(
    db: AsyncSession, *, user_id: str, amount_uzs: Decimal, provider: str, event_id: str
) -> WalletTopup:
    """Book money that already arrived outside any open top-up (an admin crediting an unmatched
    P2P transfer, spec 2026-10-19-p2p-topup): a new top-up for ``user_id`` and its attempt in
    ``provider``, settled at once through :func:`.hooks.settle`. Flushes, never commits; the
    kassa switch and the risk limits are not consulted (the money is in; the admin decided).
    """
    topup = WalletTopup(
        id=new_id(),
        number=await allocate(db, WalletTopup.number, topup_number),
        user_id=user_id,
        amount_uzs=amount_uzs,
        status="pending",
        idempotency_key=f"credit:{event_id}",
        expires_at=now() + timedelta(minutes=get_settings().topup_expiry_minutes),
    )
    db.add(topup)
    await db.flush()
    payable = await resolve(db, topup.number, lock=True)
    payment = await ensure_attempt(db, payable=payable, provider=provider)
    await settle(db, payment=payment, event_id=event_id, check_risk=False)
    log.info("payments.topup.credited_by_hand", number=topup.number, provider=provider)
    return topup


async def owned_topup(db: AsyncSession, *, user_id: str, number: str) -> WalletTopup | None:
    """``user_id``'s top-up ``number``; ``None`` when malformed, unknown or someone else's."""
    if not is_topup_number(number):
        return None
    stmt = select(WalletTopup).where(WalletTopup.number == number, WalletTopup.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def awaiting_kassa(db: AsyncSession, topup: WalletTopup) -> bool:
    """Whether ``topup`` is ``pending`` with an attempt a kassa holds (status ``pending``)."""
    if topup.status != "pending":
        return False
    held = select(Payment.id).where(Payment.topup_id == topup.id, Payment.status == "pending")
    return bool(await db.scalar(held.exists().select()))


async def topup_view(db: AsyncSession, topup: WalletTopup, *, locale: str) -> TopupView:
    """The top-up with its kassa and, while it can still be paid there, the URL to pay at."""
    first = await _first_attempt(db, topup.id)
    payable = await resolve(db, topup.number)
    current = payable.topup or topup
    provider = first.provider if first is not None else None
    if provider == P2P:
        return TopupView(
            topup=current,
            provider=provider,
            intent_url=None,
            awaiting_kassa=await awaiting_kassa(db, current),
            p2p=await _p2p_transfer(db, current),
        )
    gateway = _gateway_or_none(provider) if provider is not None else None
    return TopupView(
        topup=current,
        provider=provider,
        intent_url=await _intent(db, gateway, payable, locale),
        awaiting_kassa=await awaiting_kassa(db, current),
        fee_uzs=first.fee_uzs if first is not None else Decimal(0),
    )


async def _p2p_transfer(db: AsyncSession, topup: WalletTopup) -> P2PTransfer | None:
    """The card and exact amount of a P2P top-up, while the transfer is still awaited."""
    from csmarket.modules.p2p.api import details  # late import, see :func:`create_topup`

    found = await details(db, topup.id)
    if found is None or topup.status != "pending" or found.status != "pending":
        return None
    return P2PTransfer(
        card_number=found.card_number,
        holder=found.holder,
        amount_uzs=found.amount_uzs,
        expires_at=found.expires_at,
        status=found.status,
    )


async def dev_pay(db: AsyncSession, *, number: str) -> None:
    """Pay top-up ``number`` through ``mock`` (R11): the real ``mark_pending`` + ``settle``.

    A no-op once the top-up is paid. The caller checked ownership and the dev gate.

    Raises:
        ConflictError: ``topup_not_payable`` — expired or reversed.
    """
    payable = await resolve(db, number, lock=True)
    if payable.reason == "paid":
        return
    if not payable.payable:
        raise ConflictError("top-up cannot be paid", code="topup_not_payable")
    attempt = await ensure_attempt(db, payable=payable, provider="mock")
    await mark_pending(db, payment=attempt)
    await settle(db, payment=attempt, event_id=f"mock:{attempt.id}")


async def expire_stale(db: AsyncSession, *, limit: int = 500) -> int:
    """Expire pending top-ups past ``expires_at`` that no kassa took up (ruling R8).

    Locks the candidates ``FOR UPDATE SKIP LOCKED`` (a kassa mid-create holds its top-up,
    so it is skipped, not waited for), re-reads their attempts after the lock, and skips
    any a kassa got to in between. Every ``created`` attempt of an expired top-up is
    cancelled through :func:`.hooks.cancel_pending`. Attempts a kassa holds are left to
    that kassa's own timeout sweep. Flushes, never commits.

    Returns:
        How many top-ups went ``expired``.
    """
    held = (
        select(Payment.id)
        .where(Payment.topup_id == WalletTopup.id, Payment.status.in_(_HELD))
        .exists()
    )
    stmt = (
        select(WalletTopup)
        .where(WalletTopup.status == "pending", WalletTopup.expires_at < now(), ~held)
        .order_by(WalletTopup.expires_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    candidates = list((await db.execute(stmt)).scalars())
    if not candidates:
        return 0
    attempts_stmt = (
        select(Payment)
        .where(Payment.topup_id.in_([t.id for t in candidates]))
        .execution_options(populate_existing=True)
    )
    attempts: dict[str, list[Payment]] = {}
    for attempt in (await db.execute(attempts_stmt)).scalars():
        attempts.setdefault(str(attempt.topup_id), []).append(attempt)
    expired = 0
    for topup in candidates:
        rows = attempts.get(topup.id, [])
        if any(a.status in _HELD for a in rows):
            continue  # a kassa took it up after the candidate query's snapshot
        for attempt in rows:
            await cancel_pending(db, payment=attempt)
        topup.status = "expired"
        expired += 1
    await db.flush()
    return expired


__all__ = [
    "TopupView",
    "awaiting_kassa",
    "create_topup",
    "dev_pay",
    "expire_stale",
    "owned_topup",
    "topup_view",
]
