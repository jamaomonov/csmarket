"""The customer's own ledger lines: ``entries_for_user`` (spec §5).

Only the customer's ``user_wallet`` leg of each transaction, newest first, keyset-paged on
``(posting.created_at DESC, posting.id DESC)``. A line carries the kind, the signed amount
and the public number of what it is about — the top-up's ``T…`` number for
``topup``/``topup_reversal``, the order's number for ``purchase``/``refund``; never the actor
or the transaction metadata (an admin's identity and reason stay in admin views:
``entries_for_admin``, which shares the query and adds them).

The numbers are read through bare ``table()`` clauses, not ``payments``' or ``orders``'
models: ``wallet`` imports neither (one direction only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ColumnElement,
    ScalarSelect,
    String,
    and_,
    case,
    cast,
    column,
    func,
    or_,
    select,
    table,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ValidationError
from csmarket.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction

#: ``payments``' top-ups, as far as an entry needs them (id → public number).
_TOPUPS = table("wallet_topups", column("id", UUID(as_uuid=False)), column("number", String))
#: ``orders``' orders, as far as an entry needs them (id → public number).
_ORDERS = table("orders", column("id", UUID(as_uuid=False)), column("number", String))
#: The ``reference_type`` whose public number a line shows, and the table holding it.
_NUMBERED = {"topup": _TOPUPS, "order": _ORDERS}
#: A line's ``(reference_type, reference_id)`` → that row's public number.
Numbers = dict[tuple[str, str], str]
#: Default and largest page.
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True)
class Entry:
    """One line of the customer's balance history."""

    #: The wallet transaction's id.
    id: str
    kind: str
    #: Signed soʻm: positive when the balance grew, negative when it shrank.
    amount: Decimal
    created_at: datetime
    #: The top-up's ``T…`` number (``topup``/``topup_reversal``) or the order's number
    #: (``purchase``/``refund``); else ``None``.
    reference_number: str | None


@dataclass(frozen=True)
class AdminEntry(Entry):
    """An :class:`Entry` plus who booked it and why — never sent to the customer."""

    #: ``payments``, ``admin:<admin id>``, …
    actor: str | None
    #: ``metadata.reason`` of an admin adjustment; ``None`` otherwise.
    reason: str | None


@dataclass(frozen=True)
class EntriesPage:
    """A page of entries and the cursor for the next one (``None`` on the last)."""

    items: list[Entry]
    next_cursor: str | None


async def _numbers(
    db: AsyncSession, rows: list[tuple[WalletPosting, WalletTransaction]]
) -> Numbers:
    """The public numbers of the top-ups and orders ``rows`` refer to: one query per kind
    present on the page, none for a kind absent from it (no N+1)."""
    numbers: Numbers = {}
    for ref_type, tbl in _NUMBERED.items():
        ids = {str(t.reference_id) for _, t in rows if t.reference_type == ref_type}
        if not ids:
            continue
        found = await db.execute(select(tbl.c.id, tbl.c.number).where(tbl.c.id.in_(ids)))
        numbers.update({(ref_type, str(r.id)): str(r.number) for r in found})
    return numbers


async def _user_wallet_id(db: AsyncSession, user_id: str) -> str | None:
    return await db.scalar(
        select(WalletAccount.id).where(
            WalletAccount.owner_type == "user",
            WalletAccount.owner_id == user_id,
            WalletAccount.kind == "user_wallet",
        )
    )


async def _lines(
    db: AsyncSession, account_id: str, *, after: tuple[datetime, str] | None, limit: int
) -> tuple[list[tuple[WalletPosting, WalletTransaction]], Numbers]:
    """Up to ``limit`` postings on ``account_id`` (newest first) and their public numbers."""
    stmt = (
        select(WalletPosting, WalletTransaction)
        .join(WalletTransaction, WalletTransaction.id == WalletPosting.transaction_id)
        .where(WalletPosting.account_id == account_id)
        .order_by(WalletPosting.created_at.desc(), WalletPosting.id.desc())
        .limit(limit)
    )
    if after is not None:
        stamp, posting_id = after
        stmt = stmt.where(
            or_(
                WalletPosting.created_at < stamp,
                and_(WalletPosting.created_at == stamp, WalletPosting.id < posting_id),
            )
        )
    rows = [(p, t) for p, t in (await db.execute(stmt)).all()]
    return rows, await _numbers(db, rows)


def _entry(p: WalletPosting, t: WalletTransaction, numbers: Numbers) -> Entry:
    return Entry(
        id=t.id,
        kind=t.kind,
        # ``user_wallet`` is a debit-normal account: D grows the balance.
        amount=p.amount if p.direction == "D" else -p.amount,
        created_at=p.created_at,
        reference_number=numbers.get((t.reference_type or "", str(t.reference_id))),
    )


async def entries_for_user(
    db: AsyncSession, user_id: str, *, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> EntriesPage:
    """The user's ledger lines, newest first; empty when they have no wallet yet.

    Raises:
        ValidationError: ``limit`` outside ``1..100`` or a cursor this did not issue.
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise ValidationError("limit out of range", code="limit")
    after = decode_cursor(cursor) if cursor is not None else None
    account_id = await _user_wallet_id(db, user_id)
    if account_id is None:
        return EntriesPage(items=[], next_cursor=None)
    rows, numbers = await _lines(db, account_id, after=after, limit=limit + 1)
    page, more = rows[:limit], len(rows) > limit
    last = page[-1][0] if more else None
    return EntriesPage(
        items=[_entry(p, t, numbers) for p, t in page],
        next_cursor=encode_cursor(last.created_at, last.id) if last is not None else None,
    )


async def entries_for_admin(
    db: AsyncSession, user_id: str, *, limit: int = DEFAULT_LIMIT
) -> list[AdminEntry]:
    """The user's latest ledger lines with who booked them and why — admin views only.

    Raises:
        ValidationError: ``limit`` outside ``1..100``.
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise ValidationError("limit out of range", code="limit")
    account_id = await _user_wallet_id(db, user_id)
    if account_id is None:
        return []
    rows, numbers = await _lines(db, account_id, after=None, limit=limit)
    out: list[AdminEntry] = []
    for p, t in rows:
        e = _entry(p, t, numbers)
        reason = (t.extra_metadata or {}).get("reason")
        out.append(
            AdminEntry(
                id=e.id,
                kind=e.kind,
                amount=e.amount,
                created_at=e.created_at,
                reference_number=e.reference_number,
                actor=t.actor,
                reason=reason if isinstance(reason, str) else None,
            )
        )
    return out


def user_balance_column(
    user_id: ColumnElement[str] | InstrumentedAttribute[str],
) -> ScalarSelect[Decimal]:
    """A correlated scalar subquery: the ``user_wallet`` balance of ``user_id`` (0 if none).

    For list queries — one statement whatever the page size, no query per row.
    """
    signed = case(
        (WalletPosting.direction == "D", WalletPosting.amount), else_=-WalletPosting.amount
    )
    return (
        select(func.coalesce(func.sum(signed), 0))
        .select_from(WalletPosting)
        .join(WalletAccount, WalletAccount.id == WalletPosting.account_id)
        .where(
            WalletAccount.owner_type == "user",
            WalletAccount.kind == "user_wallet",
            WalletAccount.owner_id == cast(user_id, String),
        )
        .scalar_subquery()
    )


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "AdminEntry",
    "EntriesPage",
    "Entry",
    "entries_for_admin",
    "entries_for_user",
    "user_balance_column",
]
