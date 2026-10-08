"""Soʻm → USD: one transaction, two balanced pairs (spec 2026-10-09 §3).

UZS: C ``user_wallet`` / D ``house_fx_uzs``; USD: D ``user_wallet_usd`` / C ``house_fx_usd``.
The rate comes from the caller (``fx.api.current_usd_uzs``): ``wallet`` imports no ``fx``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, ValidationError
from csmarket.modules.wallet.models import WalletTransaction
from csmarket.modules.wallet.service import (
    InsufficientBalanceError,
    Leg,
    Reference,
    _transaction_by_key,
    balance,
    ensure_account,
    post,
    user_account,
    user_usd_account,
)

#: Largest single conversion, whole soʻm.
CONVERT_MAX_UZS = Decimal(100_000_000)


@dataclass(frozen=True)
class Conversion:
    """A booked conversion."""

    transaction_id: str
    amount_uzs: Decimal
    usd_units: Decimal
    rate: Decimal


def usd_units_for(amount_uzs: Decimal, rate: Decimal) -> Decimal:
    """Milli-USD bought by ``amount_uzs`` at ``rate`` soʻm per dollar, rounded down."""
    return (amount_uzs * 1000 / rate).to_integral_value(rounding=ROUND_FLOOR)


def _of(txn: WalletTransaction) -> Conversion:
    meta = txn.extra_metadata
    return Conversion(
        transaction_id=txn.id,
        amount_uzs=Decimal(meta["amount_uzs"]),
        usd_units=Decimal(meta["usd_units"]),
        rate=Decimal(meta["rate"]),
    )


def _same(txn: WalletTransaction, user_id: str, amount_uzs: Decimal) -> Conversion:
    meta = txn.extra_metadata
    if (
        txn.kind != "fx_convert"
        or meta.get("user_id") != user_id
        or Decimal(meta.get("amount_uzs", "-1")) != amount_uzs
    ):
        raise ConflictError(
            "this Idempotency-Key was used for another conversion", code="idempotency_mismatch"
        )
    return _of(txn)


async def convert_to_usd(
    db: AsyncSession,
    *,
    user_id: str,
    amount_uzs: Decimal,
    rate: Decimal,
    snapshot_id: str,
    idempotency_key: str,
) -> Conversion:
    """Take ``amount_uzs`` from the soʻm wallet and credit the dollars it buys at ``rate``.

    The soʻm wallet is locked ``FOR UPDATE`` before the key lookup and the balance check, so two
    conversions cannot both pass the check. A replay of the same key and amount returns the
    booked conversion; the same key with another amount or user is 409. Flushes, never commits.

    Raises:
        ValidationError: ``code="convert_amount"`` — not a positive whole soʻm within
            ``CONVERT_MAX_UZS``, or it buys less than one milli-USD ("too small").
        InsufficientBalanceError: ``code="balance_too_low"``.
        ConflictError: ``code="idempotency_mismatch"``.
    """
    if (
        not amount_uzs.is_finite()
        or amount_uzs <= 0
        or amount_uzs != amount_uzs.to_integral_value()
        or amount_uzs > CONVERT_MAX_UZS
    ):
        raise ValidationError("amount must be a positive whole soʻm", code="convert_amount")
    key = f"fx_convert:{idempotency_key}"
    wallet = await user_account(db, user_id, lock=True)
    existing = await _transaction_by_key(db, key)
    if existing is not None:
        return _same(existing, user_id, amount_uzs)
    units = usd_units_for(amount_uzs, rate)
    if units < 1:
        raise ValidationError("the amount is too small to convert", code="convert_amount")
    if await balance(db, wallet.id) < amount_uzs:
        raise InsufficientBalanceError("the balance does not cover it", code="balance_too_low")
    usd = await user_usd_account(db, user_id)
    fx_uzs = await ensure_account(db, owner_type="house", owner_id="house", kind="house_fx_uzs")
    fx_usd = await ensure_account(db, owner_type="house", owner_id="house", kind="house_fx_usd")
    txn = await post(
        db,
        kind="fx_convert",
        legs=[
            Leg(wallet.id, "C", amount_uzs),
            Leg(fx_uzs.id, "D", amount_uzs),
            Leg(usd.id, "D", units),
            Leg(fx_usd.id, "C", units),
        ],
        idempotency_key=key,
        reference=Reference(type="fx_snapshot", id=snapshot_id),
        actor=f"user:{user_id}",
        metadata={
            "user_id": user_id,
            "amount_uzs": str(amount_uzs),
            "usd_units": str(units),
            "rate": str(rate),
        },
    )
    return _same(txn, user_id, amount_uzs)
