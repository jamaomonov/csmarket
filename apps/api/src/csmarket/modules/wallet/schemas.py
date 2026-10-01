"""Wire shapes for the customer's ``/wallet`` (balance and entries)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from csmarket.core.money import wire_uzs
from csmarket.modules.wallet.entries import EntriesPage, Entry


class BalanceOut(BaseModel):
    """The customer's spendable balance."""

    #: Whole soʻm as digits.
    balance_uzs: str

    @classmethod
    def of(cls, amount: Decimal) -> BalanceOut:
        """Build from the ledger balance."""
        return cls(balance_uzs=wire_uzs(amount))


class EntryOut(BaseModel):
    """One line of the balance history. No actor, no metadata (customer view)."""

    id: str
    kind: Literal["topup", "topup_reversal", "admin_adjust", "purchase", "refund"]
    #: Signed whole soʻm: ``+50000`` credited, ``-10000`` debited.
    amount_uzs: str
    created_at: datetime
    #: The top-up's number for ``topup``/``topup_reversal``; else ``null``.
    reference_number: str | None

    @classmethod
    def of(cls, entry: Entry) -> EntryOut:
        """Build from a ledger :class:`Entry`."""
        digits = wire_uzs(abs(entry.amount))
        return cls(
            id=entry.id,
            kind=entry.kind,  # type: ignore[arg-type]  # post() admits only TX_KINDS
            amount_uzs=f"+{digits}" if entry.amount > 0 else f"-{digits}",
            created_at=entry.created_at,
            reference_number=entry.reference_number,
        )


class EntriesOut(BaseModel):
    """A page of entries, newest first, and the cursor for the next (``null`` on the last)."""

    items: list[EntryOut]
    next_cursor: str | None

    @classmethod
    def of(cls, page: EntriesPage) -> EntriesOut:
        """Build from an :class:`EntriesPage`."""
        return cls(items=[EntryOut.of(e) for e in page.items], next_cursor=page.next_cursor)


__all__ = ["BalanceOut", "EntriesOut", "EntryOut"]
