"""One sale's P&L and its reconciliation flag (spec 2026-10-13-sales-pnl) — pure, no I/O.

Income is what Skinslink credited us (``amount_usd``); a sale Skinslink rolled back after we
paid, or one with no credited amount, brings nothing. Costs are soʻm (owner rulings):

- a payout to the balance costs ``payout_uzs`` (bonus included) at once;
- a paid card request costs ``amount_uzs`` plus the bank's charge to the sender
  (``bank_fee_uzs``, or ``bank_fee_pct`` of the amount for a row paid before the column);
- a rejected card request costs ``items_uzs`` (what the balance got instead);
- a request still waiting (``waiting_hold`` / ``to_pay``) costs its amount plus the expected
  bank fee, shown apart as «к выплате»;
- a canceled request (a rollback) costs nothing.

Soʻm convert to USD at the CBU rate of the sale's creation (``cbu_rate``), never our cut sale
rate; a sale without a snapshot before it falls back to its own ``rate``.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

ReconFlag = Literal["short", "missing", "reverted"]

_HUNDRED = Decimal(100)
_ZERO = Decimal(0)
_USD = Decimal("0.000001")
#: Skinslink may credit down to 99 % of our quote (``pricing.MIN_PRICE_SHARE``).
_SHORT_SHARE = Decimal("0.99")
_COMPLETED = frozenset({"credited", "payout"})
_REVERTED = frozenset({"rolled_back", "late_deposit"})


class PnlRow(BaseModel):
    """One sale as the P&L reads it, with its card request if any."""

    model_config = ConfigDict(frozen=True)

    payout_to: str
    status: str
    attention_reason: str | None
    quoted_usd: Decimal
    amount_usd: Decimal | None
    items_uzs: Decimal
    payout_uzs: Decimal
    rate: Decimal
    cbu_rate: Decimal | None
    request_status: str | None = None
    request_amount_uzs: Decimal | None = None
    request_fee_uzs: Decimal | None = None
    request_bank_fee_uzs: Decimal | None = None


class SalePnl(BaseModel):
    """One sale's income and costs."""

    model_config = ConfigDict(frozen=True)

    income_usd: Decimal = _ZERO
    #: ``income_usd`` at the sale's CBU rate, whole soʻm.
    income_uzs: Decimal = _ZERO
    #: Paid card transfers, the bank's charge included.
    to_cards_uzs: Decimal = _ZERO
    #: Payouts to the balance (bonus included) and rejected card requests.
    to_balances_uzs: Decimal = _ZERO
    #: Card requests not paid yet, the expected bank fee included.
    to_pay_uzs: Decimal = _ZERO
    #: The card fee kept from the seller (paid or pending requests).
    withheld_uzs: Decimal = _ZERO
    #: The bank's charge (paid or expected).
    bank_uzs: Decimal = _ZERO
    cost_uzs: Decimal = _ZERO
    cost_usd: Decimal = _ZERO


def bank_fee(amount_uzs: Decimal, pct: Decimal) -> Decimal:
    """The bank's charge on sending ``amount_uzs``, whole soʻm rounded up."""
    return (amount_uzs * pct / _HUNDRED).to_integral_value(rounding=ROUND_CEILING)


def _income(row: PnlRow) -> Decimal:
    if row.attention_reason == "rolled_back" or row.amount_usd is None:
        return _ZERO
    return row.amount_usd


def _costs(row: PnlRow, bank_fee_pct: Decimal) -> dict[str, Decimal]:
    """The soʻm cost lines of ``row`` (keys of :class:`SalePnl`)."""
    if row.request_status is None:
        return {"to_balances_uzs": row.payout_uzs} if row.payout_to == "balance" else {}
    amount = row.request_amount_uzs or _ZERO
    withheld = row.request_fee_uzs or _ZERO
    match row.request_status:
        case "paid":
            fee = (
                row.request_bank_fee_uzs
                if row.request_bank_fee_uzs is not None
                else bank_fee(amount, bank_fee_pct)
            )
            return {"to_cards_uzs": amount + fee, "withheld_uzs": withheld, "bank_uzs": fee}
        case "waiting_hold" | "to_pay":
            fee = bank_fee(amount, bank_fee_pct)
            return {"to_pay_uzs": amount + fee, "withheld_uzs": withheld, "bank_uzs": fee}
        case "rejected":
            return {"to_balances_uzs": row.items_uzs}
        case _:
            return {}


def sale_pnl(row: PnlRow, bank_fee_pct: Decimal) -> SalePnl:
    """The P&L of one sale counted in a window (credited by Skinslink)."""
    lines = _costs(row, bank_fee_pct)
    cost = (
        lines.get("to_cards_uzs", _ZERO)
        + lines.get("to_balances_uzs", _ZERO)
        + lines.get("to_pay_uzs", _ZERO)
    )
    rate = row.cbu_rate or row.rate
    income = _income(row)
    return SalePnl(
        income_usd=income,
        income_uzs=(income * rate).quantize(Decimal(1)),
        cost_uzs=cost,
        cost_usd=(cost / rate).quantize(_USD),
        **lines,
    )


def flag(row: PnlRow) -> ReconFlag | None:
    """What is wrong with the sale's Skinslink credit, if anything (a revert first)."""
    if row.attention_reason in _REVERTED:
        return "reverted"
    if row.status in _COMPLETED and row.amount_usd is None:
        return "missing"
    if row.amount_usd is not None and row.amount_usd < row.quoted_usd * _SHORT_SHARE:
        return "short"
    return None


__all__ = ["PnlRow", "ReconFlag", "SalePnl", "bank_fee", "flag", "sale_pnl"]
