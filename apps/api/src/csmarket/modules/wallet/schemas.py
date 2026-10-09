"""Wire shapes for the customer's ``/wallet`` (balance and entries)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from csmarket.core.money import wire_usd, wire_uzs
from csmarket.modules.wallet.convert import Conversion
from csmarket.modules.wallet.entries import EntriesPage, Entry
from csmarket.modules.wallet.service import Currency


class UsdWalletOut(BaseModel):
    """The dollar wallet; present only once an admin switched it on."""

    #: Dollars with three decimals, e.g. ``"7.826"``.
    balance_usd: str
    #: Soʻm per dollar for a conversion now, two decimals; ``null`` without a fresh rate.
    rate_uzs: str | None


class BalanceOut(BaseModel):
    """The customer's spendable balance."""

    #: Whole soʻm as digits.
    balance_uzs: str
    #: The dollar wallet; ``null`` unless it is switched on for this account.
    usd: UsdWalletOut | None = None

    @classmethod
    def of(
        cls, amount: Decimal, *, usd: Decimal | None = None, rate: Decimal | None = None
    ) -> BalanceOut:
        """Build from the ledger balance(s); ``usd=None`` means the dollar wallet is off."""
        block = (
            None
            if usd is None
            else UsdWalletOut(
                balance_usd=wire_usd(usd),
                rate_uzs=None if rate is None else format(rate.quantize(Decimal("0.01")), "f"),
            )
        )
        return cls(balance_uzs=wire_uzs(amount), usd=block)


class ConvertIn(BaseModel):
    """Soʻm to move into the dollar wallet."""

    model_config = ConfigDict(extra="forbid")

    amount_uzs: Annotated[int, Field(strict=True, ge=1000, le=100_000_000)]


class ConvertOut(BaseModel):
    """A booked conversion and both balances after it."""

    amount_uzs: str
    amount_usd: str
    rate_uzs: str
    balance_uzs: str
    balance_usd: str

    @classmethod
    def of(cls, conv: Conversion, *, uzs: Decimal, usd: Decimal) -> ConvertOut:
        """Build from the :class:`Conversion` and the balances after it."""
        return cls(
            amount_uzs=wire_uzs(conv.amount_uzs),
            amount_usd=wire_usd(conv.usd_units),
            rate_uzs=format(conv.rate.quantize(Decimal("0.01")), "f"),
            balance_uzs=wire_uzs(uzs),
            balance_usd=wire_usd(usd),
        )


class EntryOut(BaseModel):
    """One line of the balance history. No actor, no metadata (customer view)."""

    id: str
    kind: Literal[
        "topup",
        "topup_reversal",
        "admin_adjust",
        "purchase",
        "refund",
        "sale_credit",
        "payout_return",
        "fx_convert",
        "admin_adjust_usd",
    ]
    currency: Currency = "UZS"
    #: Signed whole soʻm: ``+50000`` credited, ``-10000`` debited; ``"0"`` on a dollar line.
    amount_uzs: str
    #: Signed dollars (``+7.826``) on a dollar line; ``null`` on a soʻm line.
    amount_usd: str | None = None
    created_at: datetime
    #: The top-up's number for ``topup``/``topup_reversal``, the order's number for
    #: ``purchase``/``refund``, the sale's number for ``sale_credit``/``payout_return``; else
    #: ``null``.
    reference_number: str | None

    @classmethod
    def of(cls, entry: Entry, currency: Currency = "UZS") -> EntryOut:
        """Build from a ledger :class:`Entry` of the ``currency`` wallet."""
        sign = "+" if entry.amount > 0 else "-"
        usd = currency == "USD"
        digits = wire_uzs(abs(entry.amount))
        return cls(
            id=entry.id,
            kind=entry.kind,  # type: ignore[arg-type]  # post() admits only TX_KINDS
            currency=currency,
            amount_uzs="0" if usd else f"{sign}{digits}",
            amount_usd=f"{sign}{wire_usd(abs(entry.amount))}" if usd else None,
            created_at=entry.created_at,
            reference_number=entry.reference_number,
        )


class EntriesOut(BaseModel):
    """A page of entries, newest first, and the cursor for the next (``null`` on the last)."""

    items: list[EntryOut]
    next_cursor: str | None

    @classmethod
    def of(cls, page: EntriesPage, currency: Currency = "UZS") -> EntriesOut:
        """Build from an :class:`EntriesPage` of the ``currency`` wallet."""
        return cls(
            items=[EntryOut.of(e, currency) for e in page.items], next_cursor=page.next_cursor
        )


__all__ = ["BalanceOut", "ConvertIn", "ConvertOut", "EntriesOut", "EntryOut", "UsdWalletOut"]
