"""The payable resolver (ruling R5): a kassa's account value → what is being paid.

Every kassa passes the number it received (Click ``merchant_trans_id``, Payme
``account.order``, Uzum ``params.order``) through :func:`resolve`; nothing else loads a
top-up or an order by number for a kassa. ``T…`` is a top-up; any other well-formed number
is an order (M4a).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.numbers import TOPUP_PREFIX, is_number, is_topup_number
from csmarket.modules.orders.api import Order
from csmarket.modules.payments.models import WalletTopup

Kind = Literal["topup", "order"]
Reason = Literal["ok", "paid", "expired", "reversed", "not_found"]

#: A top-up status that is not payable, and why.
_REFUSED: dict[str, Reason] = {"succeeded": "paid", "expired": "expired", "reversed": "reversed"}


@dataclass(frozen=True)
class Payable:
    """The thing an account value names, and whether a kassa may take money for it.

    Exactly one of ``topup`` and ``order`` is set, by ``kind``; for ``not_found`` both are
    ``None``, the amount is ``0`` and ``user_id`` is empty.
    """

    kind: Kind
    number: str
    amount_uzs: Decimal
    user_id: str
    payable: bool
    reason: Reason
    topup: WalletTopup | None
    order: Order | None = None


def _not_found(account: str) -> Payable:
    kind: Kind = "topup" if account.startswith(TOPUP_PREFIX) else "order"
    return Payable(
        kind=kind,
        number=account,
        amount_uzs=Decimal(0),
        user_id="",
        payable=False,
        reason="not_found",
        topup=None,
    )


def _topup_reason(topup: WalletTopup) -> Reason:
    """``ok`` for a pending top-up still inside its window, else why it is refused."""
    refused = _REFUSED.get(topup.status)
    if refused is not None:
        return refused
    return "ok" if topup.expires_at > now() else "expired"


def _order_reason(order: Order) -> Reason:
    """``ok`` for a pending order inside its window; ``expired`` past it or ``cancelled``;
    ``paid`` for every later status (the money already came)."""
    if order.status == "pending":
        return "ok" if order.expires_at > now() else "expired"
    if order.status == "cancelled":
        return "expired"
    return "paid"


async def _resolve_topup(db: AsyncSession, account: str, *, lock: bool) -> Payable:
    stmt = select(WalletTopup).where(WalletTopup.number == account)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    topup = (await db.execute(stmt)).scalar_one_or_none()
    if topup is None:
        return _not_found(account)
    reason = _topup_reason(topup)
    return Payable(
        kind="topup",
        number=topup.number,
        amount_uzs=topup.amount_uzs,
        user_id=topup.user_id,
        payable=reason == "ok",
        reason=reason,
        topup=topup,
    )


async def _resolve_order(db: AsyncSession, account: str, *, lock: bool) -> Payable:
    stmt = select(Order).where(Order.number == account)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        return _not_found(account)
    reason = _order_reason(order)
    return Payable(
        kind="order",
        number=order.number,
        amount_uzs=order.price_uzs,
        user_id=order.user_id,
        payable=reason == "ok",
        reason=reason,
        topup=None,
        order=order,
    )


async def resolve(db: AsyncSession, account: str, *, lock: bool = False) -> Payable:
    """Resolve a kassa's account value.

    A pending top-up or order past ``expires_at`` is ``expired`` even before its sweep
    marks it; a cancelled order is ``expired`` too; an order past ``pending`` (``paid``,
    ``buying``, …) is ``paid``.

    Args:
        db: Session.
        account: The value the kassa sent, verbatim (no case folding).
        lock: Read the top-up or order ``FOR UPDATE`` (re-read even if already in the
            session) — for a caller about to create or move an attempt on it. Lock order
            everywhere: the top-up or order, then the kassa row, then its payment rows.
    """
    if is_topup_number(account):
        return await _resolve_topup(db, account, lock=lock)
    if is_number(account):
        return await _resolve_order(db, account, lock=lock)
    return _not_found(account)


__all__ = ["Kind", "Payable", "Reason", "resolve"]
