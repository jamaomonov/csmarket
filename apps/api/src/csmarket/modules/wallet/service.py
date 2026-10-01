"""Wallet service: the ledger primitives (spec §5, rulings R1, R2).

This is the **only** writer of ``wallet_accounts``, ``wallet_transactions`` and
``wallet_postings``. Every balance change is one :func:`post` with at least two legs whose
debits equal their credits, under one idempotency key per business event. UZS only, whole
soʻm. Other modules call these through ``wallet.api``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.modules.wallet.models import (
    OWNER_TYPES,
    WalletAccount,
    WalletPosting,
    WalletTransaction,
)

log = get_logger("csmarket.wallet.service")

Direction = Literal["D", "C"]

#: Normal side of each account kind (ruling R2). Balance = SUM(normal) − SUM(other side).
NORMAL_SIDE: dict[str, Direction] = {
    # A customer's spendable soʻm.
    "user_wallet": "D",
    # What an acquirer (owner = provider slug) owes us for money it collected.
    "provider_clearing": "C",
    # Debit partner of ``user_wallet`` when an order is paid from the balance (M4).
    "house_payments_received": "D",
    # Contra-account of admin balance adjustments.
    "house_adjustments": "D",
}

#: Transaction kinds (spec §5). M4 adds ``purchase`` and ``refund``.
TX_KINDS: tuple[str, ...] = ("topup", "topup_reversal", "admin_adjust")

#: ``numeric(14,0)`` holds at most 14 digits.
_MAX_AMOUNT = Decimal(10) ** 14


class InsufficientBalanceError(ConflictError):
    """The balance does not cover the amount; raised by callers that debit a user wallet."""

    type_uri = "https://csmarket.uz/errors/insufficient-balance"
    title = "Insufficient balance"


@dataclass(frozen=True)
class Leg:
    """One posting of a transaction: which account, which side, how many soʻm."""

    account_id: str
    direction: Direction
    amount: Decimal


@dataclass(frozen=True)
class Reference:
    """What a transaction is about (a top-up, an order, an admin action, …)."""

    type: str
    id: str


def _validate_leg(leg: Leg) -> None:
    """Refuse a leg with a bad side or an amount that is not a positive whole soʻm."""
    if leg.direction not in ("D", "C"):
        raise ValidationError("leg direction must be D or C", direction=str(leg.direction))
    if not leg.amount.is_finite() or leg.amount <= 0:
        raise ValidationError("leg amount must be positive", amount=str(leg.amount))
    if leg.amount != leg.amount.to_integral_value():
        raise ValidationError("ledger amounts are whole soʻm", amount=str(leg.amount))
    if leg.amount >= _MAX_AMOUNT:
        raise ValidationError("leg amount is too large", amount=str(leg.amount))


def _validate_legs(legs: list[Leg]) -> None:
    """At least two legs, each valid, and ``SUM(D) == SUM(C)``."""
    if len(legs) < 2:
        raise ValidationError("a wallet transaction needs at least 2 legs")
    sums = {"D": Decimal(0), "C": Decimal(0)}
    for leg in legs:
        _validate_leg(leg)
        sums[leg.direction] += leg.amount
    if sums["D"] != sums["C"]:
        raise ValidationError(
            "ledger invariant break: SUM(D) != SUM(C)",
            debit=str(sums["D"]),
            credit=str(sums["C"]),
        )


async def _find_account(
    db: AsyncSession, *, owner_type: str, owner_id: str, kind: str
) -> WalletAccount | None:
    """The account for this tuple, or ``None``."""
    stmt = select(WalletAccount).where(
        WalletAccount.owner_type == owner_type,
        WalletAccount.owner_id == owner_id,
        WalletAccount.kind == kind,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def ensure_account(
    db: AsyncSession, *, owner_type: str, owner_id: str, kind: str
) -> WalletAccount:
    """Find the account for ``(owner_type, owner_id, kind)`` or create it.

    Race-safe: the insert runs in a SAVEPOINT, so losing to a concurrent creator (the
    unique key) rolls back only that insert — never the caller's transaction — and the
    winner's row is returned.

    Raises:
        ValidationError: unknown owner type or account kind.
    """
    if owner_type not in OWNER_TYPES:
        raise ValidationError("unknown account owner type", owner_type=owner_type)
    if kind not in NORMAL_SIDE:
        raise ValidationError("unknown account kind", kind=kind)
    existing = await _find_account(db, owner_type=owner_type, owner_id=owner_id, kind=kind)
    if existing is not None:
        return existing
    account = WalletAccount(id=new_id(), owner_type=owner_type, owner_id=owner_id, kind=kind)
    try:
        async with db.begin_nested():
            db.add(account)
            await db.flush()
    except IntegrityError:
        winner = await _find_account(db, owner_type=owner_type, owner_id=owner_id, kind=kind)
        if winner is None:  # the integrity error was something else
            raise
        return winner
    return account


async def user_account(db: AsyncSession, user_id: str, *, lock: bool = False) -> WalletAccount:
    """The user's ``user_wallet`` account, created on first use.

    With ``lock=True`` the row is re-read ``FOR UPDATE``: a caller that checks the balance
    before debiting it holds this lock until commit, so two debits cannot both pass the
    check (no overdraft by our code).
    """
    account = await ensure_account(db, owner_type="user", owner_id=user_id, kind="user_wallet")
    if not lock:
        return account
    stmt = (
        select(WalletAccount)
        .where(WalletAccount.id == account.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _transaction_by_key(db: AsyncSession, idempotency_key: str) -> WalletTransaction | None:
    """The transaction posted under ``idempotency_key``, or ``None``."""
    stmt = select(WalletTransaction).where(WalletTransaction.idempotency_key == idempotency_key)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _check_accounts(db: AsyncSession, legs: list[Leg]) -> None:
    """Every leg's account exists and is ``active``."""
    ids = {leg.account_id for leg in legs}
    rows = (await db.execute(select(WalletAccount).where(WalletAccount.id.in_(ids)))).scalars()
    by_id = {a.id: a for a in rows}
    if len(by_id) != len(ids):
        raise NotFoundError("wallet account not found")
    for account in by_id.values():
        if account.status != "active":
            raise ConflictError("wallet account is frozen", account_id=account.id)


async def post(
    db: AsyncSession,
    *,
    kind: str,
    legs: list[Leg],
    idempotency_key: str,
    reference: Reference | None = None,
    actor: str = "system",
    metadata: dict[str, Any] | None = None,  # Any: JSON scalars, never PII
) -> WalletTransaction:
    """Post one balanced transaction, all or nothing; flushes, never commits.

    A key already used returns that transaction unchanged (replay), whatever the legs —
    callers derive the key from the business event (``topup:{topup_id}``, …), so the
    second call is the same event. A concurrent post of the same key loses inside a
    SAVEPOINT and also returns the winner's transaction; the caller's transaction is
    untouched.

    Raises:
        ValidationError: unknown kind, fewer than two legs, a leg that is not a positive
            whole soʻm, or ``SUM(D) != SUM(C)``.
        NotFoundError: a leg names an account that does not exist.
        ConflictError: a leg's account is frozen.
    """
    existing = await _transaction_by_key(db, idempotency_key)
    if existing is not None:
        return existing
    if kind not in TX_KINDS:
        raise ValidationError("unknown wallet transaction kind", kind=kind)
    _validate_legs(legs)
    await _check_accounts(db, legs)

    txn = WalletTransaction(
        id=new_id(),
        kind=kind,
        reference_type=reference.type if reference else None,
        reference_id=reference.id if reference else None,
        idempotency_key=idempotency_key,
        actor=actor,
        extra_metadata=metadata or {},
    )
    try:
        async with db.begin_nested():
            db.add(txn)
            await db.flush()
            db.add_all(
                WalletPosting(
                    id=new_id(),
                    transaction_id=txn.id,
                    account_id=leg.account_id,
                    direction=leg.direction,
                    amount=leg.amount,
                )
                for leg in legs
            )
            await db.flush()
    except IntegrityError:
        winner = await _transaction_by_key(db, idempotency_key)
        if winner is None:  # the integrity error was something else
            raise
        return winner
    total = sum((leg.amount for leg in legs if leg.direction == "D"), Decimal(0))
    log.info("wallet.posted", kind=kind, transaction_id=txn.id, amount=str(total))
    return txn


async def balance(db: AsyncSession, account_id: str) -> Decimal:
    """The account's balance on its normal side, in whole soʻm.

    Raises:
        NotFoundError: no such account.
    """
    kind = await db.scalar(select(WalletAccount.kind).where(WalletAccount.id == account_id))
    if kind is None:
        raise NotFoundError("wallet account not found")
    normal = NORMAL_SIDE[kind]
    signed = case(
        (WalletPosting.direction == normal, WalletPosting.amount), else_=-WalletPosting.amount
    )
    total = await db.scalar(
        select(func.coalesce(func.sum(signed), 0)).where(WalletPosting.account_id == account_id)
    )
    return Decimal(total or 0)


async def user_balance(db: AsyncSession, user_id: str) -> Decimal:
    """The user's spendable soʻm; ``0`` when they have no wallet yet (none is created)."""
    account = await _find_account(db, owner_type="user", owner_id=user_id, kind="user_wallet")
    if account is None:
        return Decimal(0)
    return await balance(db, account.id)


async def _provider_clearing(db: AsyncSession, provider: str) -> WalletAccount:
    """The kassa's clearing account (owner = provider slug)."""
    return await ensure_account(
        db, owner_type="provider", owner_id=provider, kind="provider_clearing"
    )


async def credit_topup(
    db: AsyncSession, *, user_id: str, topup_id: str, amount: Decimal, provider: str
) -> WalletTransaction:
    """Book a paid top-up: D ``user_wallet`` / C ``provider_clearing:<provider>``.

    At most once per top-up, whatever the retries: the key is ``topup:{topup_id}``, so a
    second call returns the first transaction. Flushes, never commits.
    """
    wallet = await user_account(db, user_id)
    clearing = await _provider_clearing(db, provider)
    return await post(
        db,
        kind="topup",
        legs=[Leg(wallet.id, "D", amount), Leg(clearing.id, "C", amount)],
        idempotency_key=f"topup:{topup_id}",
        reference=Reference(type="topup", id=topup_id),
        actor="payments",
        metadata={"provider": provider},
    )


async def reverse_topup(
    db: AsyncSession, *, user_id: str, topup_id: str, amount: Decimal, provider: str
) -> WalletTransaction:
    """Claw a top-up back: D ``provider_clearing:<provider>`` / C ``user_wallet``.

    Never drives the balance below zero: the user's wallet is locked ``FOR UPDATE`` and the
    reversal is refused when the balance no longer covers ``amount`` (the money was spent).
    A reversal already booked (key ``topup_reversal:{topup_id}``) is returned as is, before
    any balance check. Flushes, never commits.

    Raises:
        InsufficientBalanceError: the balance is below ``amount``.
    """
    key = f"topup_reversal:{topup_id}"
    existing = await _transaction_by_key(db, key)
    if existing is not None:
        return existing
    wallet = await user_account(db, user_id, lock=True)
    if await balance(db, wallet.id) < amount:
        raise InsufficientBalanceError("the top-up was already spent", amount=str(amount))
    clearing = await _provider_clearing(db, provider)
    return await post(
        db,
        kind="topup_reversal",
        legs=[Leg(clearing.id, "D", amount), Leg(wallet.id, "C", amount)],
        idempotency_key=key,
        reference=Reference(type="topup", id=topup_id),
        actor="payments",
        metadata={"provider": provider},
    )
