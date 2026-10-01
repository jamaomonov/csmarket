"""Short public numbers (spec §6): 8 Crockford base32 chars, random, never sequential.

Orders (M4) and top-ups share the namespace the kassas see in the account field: a top-up is
``T`` + 7 chars, so an order number must never start with ``T`` — the payable resolver
(``payments.payable``) tells them apart by that one letter.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
TOPUP_PREFIX = "T"
_FIRST = ALPHABET.replace(TOPUP_PREFIX, "")
_LEN = 8


def _chars(n: int, alphabet: str = ALPHABET) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


def order_number() -> str:
    """An order number: 8 chars, the first never ``T``."""
    return secrets.choice(_FIRST) + _chars(_LEN - 1)


def topup_number() -> str:
    """A top-up number: ``T`` + 7 chars."""
    return TOPUP_PREFIX + _chars(_LEN - 1)


def is_number(value: str) -> bool:
    """Whether ``value`` is 8 chars, all from the alphabet (upper case)."""
    return len(value) == _LEN and all(c in ALPHABET for c in value)


def is_topup_number(value: str) -> bool:
    """Whether ``value`` is a well-formed top-up number."""
    return is_number(value) and value.startswith(TOPUP_PREFIX)


async def allocate(
    db: AsyncSession,
    column: Any,  # Any: an InstrumentedAttribute of any model's unique number column
    make: Callable[[], str],
    *,
    attempts: int = 3,
) -> str:
    """A fresh number not yet in ``column`` (32⁷ ≈ 3.4 × 10¹⁰ — collisions are rare).

    The unique index is still the real guard; this only keeps a collision from becoming
    a failed request.

    Raises:
        RuntimeError: every one of ``attempts`` candidates was already taken.
    """
    for _ in range(attempts):
        candidate = make()
        taken = await db.scalar(select(exists().where(column == candidate)))
        if not taken:
            return candidate
    raise RuntimeError("could not allocate a unique number")
