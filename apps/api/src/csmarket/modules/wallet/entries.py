"""The customer's own ledger lines: ``entries_for_user`` (spec §5).

Only the customer's ``user_wallet`` leg of each transaction, newest first, keyset-paged on
``(posting.created_at DESC, posting.id DESC)``. A line carries the kind, the signed amount
and — for ``topup``/``topup_reversal`` — the top-up's public number; never the actor or the
transaction metadata (an admin's identity and reason stay in admin views).

The top-up number is read through a bare ``table()`` clause, not ``payments``' model:
``wallet`` never imports ``payments`` (one direction only).
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, and_, column, or_, select, table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ValidationError
from csmarket.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction

#: ``payments``' top-ups, as far as an entry needs them (id → public number).
_TOPUPS = table("wallet_topups", column("id", UUID(as_uuid=False)), column("number", String))
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
    #: The top-up's ``T…`` number for ``topup``/``topup_reversal``; else ``None``.
    reference_number: str | None


@dataclass(frozen=True)
class EntriesPage:
    """A page of entries and the cursor for the next one (``None`` on the last)."""

    items: list[Entry]
    next_cursor: str | None


def _encode_cursor(created_at: datetime, posting_id: str) -> str:
    raw = json.dumps([created_at.isoformat(), posting_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(token: str) -> tuple[datetime, str]:
    """Inverse of :func:`_encode_cursor`; anything else is a 422, not a 500."""
    try:
        padded = token + "=" * (-len(token) % 4)
        stamp, posting_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        return datetime.fromisoformat(stamp), str(uuid.UUID(posting_id))
    except (binascii.Error, ValueError, UnicodeDecodeError, TypeError) as exc:
        raise ValidationError("invalid cursor", code="cursor") from exc


async def _topup_numbers(db: AsyncSession, topup_ids: set[str]) -> dict[str, str]:
    if not topup_ids:
        return {}
    rows = await db.execute(
        select(_TOPUPS.c.id, _TOPUPS.c.number).where(_TOPUPS.c.id.in_(topup_ids))
    )
    return {str(row.id): str(row.number) for row in rows}


async def entries_for_user(
    db: AsyncSession, user_id: str, *, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> EntriesPage:
    """The user's ledger lines, newest first; empty when they have no wallet yet.

    Raises:
        ValidationError: ``limit`` outside ``1..100`` or a cursor this did not issue.
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise ValidationError("limit out of range", code="limit")
    after = _decode_cursor(cursor) if cursor is not None else None
    account_id = await db.scalar(
        select(WalletAccount.id).where(
            WalletAccount.owner_type == "user",
            WalletAccount.owner_id == user_id,
            WalletAccount.kind == "user_wallet",
        )
    )
    if account_id is None:
        return EntriesPage(items=[], next_cursor=None)
    stmt = (
        select(WalletPosting, WalletTransaction)
        .join(WalletTransaction, WalletTransaction.id == WalletPosting.transaction_id)
        .where(WalletPosting.account_id == account_id)
        .order_by(WalletPosting.created_at.desc(), WalletPosting.id.desc())
        .limit(limit + 1)
    )
    if after is not None:
        stamp, posting_id = after
        stmt = stmt.where(
            or_(
                WalletPosting.created_at < stamp,
                and_(WalletPosting.created_at == stamp, WalletPosting.id < posting_id),
            )
        )
    rows = list((await db.execute(stmt)).all())
    page, more = rows[:limit], len(rows) > limit
    numbers = await _topup_numbers(
        db, {str(t.reference_id) for _, t in page if t.reference_type == "topup"}
    )
    items = [
        Entry(
            id=t.id,
            kind=t.kind,
            # ``user_wallet`` is a debit-normal account: D grows the balance.
            amount=p.amount if p.direction == "D" else -p.amount,
            created_at=p.created_at,
            reference_number=numbers.get(str(t.reference_id))
            if t.reference_type == "topup"
            else None,
        )
        for p, t in page
    ]
    last = page[-1][0] if more else None
    return EntriesPage(
        items=items,
        next_cursor=_encode_cursor(last.created_at, last.id) if last is not None else None,
    )


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "EntriesPage", "Entry", "entries_for_user"]
