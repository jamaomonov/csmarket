"""The payable resolver (ruling R5): a kassa's account value → what is being paid.

Every kassa passes the number it received (Click ``merchant_trans_id``, Payme
``account.order``, Uzum ``params.order``) through :func:`resolve`; nothing else loads a
top-up by number. ``T…`` is a top-up; any other value is an order — M4; until then
``not_found``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.numbers import TOPUP_PREFIX, is_topup_number
from csmarket.modules.payments.models import WalletTopup

Kind = Literal["topup", "order"]
Reason = Literal["ok", "paid", "expired", "reversed", "not_found"]

#: A top-up status that is not payable, and why.
_REFUSED: dict[str, Reason] = {"succeeded": "paid", "expired": "expired", "reversed": "reversed"}


@dataclass(frozen=True)
class Payable:
    """The thing an account value names, and whether a kassa may take money for it.

    For ``not_found`` the amount is ``0``, ``user_id`` is empty and ``topup`` is ``None``.
    """

    kind: Kind
    number: str
    amount_uzs: Decimal
    user_id: str
    payable: bool
    reason: Reason
    topup: WalletTopup | None


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


def _reason(topup: WalletTopup) -> Reason:
    """``ok`` for a pending top-up still inside its window, else why it is refused."""
    refused = _REFUSED.get(topup.status)
    if refused is not None:
        return refused
    return "ok" if topup.expires_at > now() else "expired"


async def resolve(db: AsyncSession, account: str, *, lock: bool = False) -> Payable:
    """Resolve a kassa's account value.

    A pending top-up past ``expires_at`` is ``expired`` even before the sweep marks it.

    Args:
        db: Session.
        account: The value the kassa sent, verbatim (no case folding).
        lock: Read the top-up ``FOR UPDATE`` (re-read even if already in the session) —
            for a caller about to create or move an attempt on it. Lock order everywhere:
            top-up, then its payment rows.
    """
    if not is_topup_number(account):
        return _not_found(account)
    stmt = select(WalletTopup).where(WalletTopup.number == account)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    topup = (await db.execute(stmt)).scalar_one_or_none()
    if topup is None:
        return _not_found(account)
    reason = _reason(topup)
    return Payable(
        kind="topup",
        number=topup.number,
        amount_uzs=topup.amount_uzs,
        user_id=topup.user_id,
        payable=reason == "ok",
        reason=reason,
        topup=topup,
    )


__all__ = ["Kind", "Payable", "Reason", "resolve"]
