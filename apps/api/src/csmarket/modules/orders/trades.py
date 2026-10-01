"""An order's Waxpeer trade as we keep it: :func:`mirror` a lookup onto ``skin_trades`` and
:func:`pick_trade` ours among the trades under one ``project_id``.

Shared by the buy (``orders.buying``: a lookup that finds an earlier purchase adopts it) and
the trade sweeps (M4a Task 9 adds ``apply`` here). Callers hold the order row and then the
trade row ``FOR UPDATE`` (ruling K) before :func:`mirror` writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from csmarket.core.clock import now
from csmarket.modules.orders.models import SkinTrade
from csmarket.modules.skins.api import WaxpeerTrade

#: Waxpeer's status of a failed or returned trade.
FAILED_STATUS = 6


class AmbiguousTradeError(Exception):
    """Several live trades under our ``project_id`` and no Waxpeer id to tell ours."""


def pick_trade(trades: Sequence[WaxpeerTrade], waxpeer_id: int | None) -> WaxpeerTrade | None:
    """Our trade among those a lookup returned for one ``project_id``.

    Waxpeer keeps a refused attempt under the same ``project_id`` (status 6), so: by
    Waxpeer's id when we know it; else the only trade; else the only one still alive; when
    every one failed, the last.

    Args:
        trades: The lookup's trades for one ``project_id``.
        waxpeer_id: The id the buy answer or an earlier lookup gave us, if any.

    Returns:
        The trade, or ``None`` when there is none (or none with ``waxpeer_id``).

    Raises:
        AmbiguousTradeError: several live trades and no id to choose by.
    """
    if waxpeer_id:
        return next((t for t in trades if t.id == waxpeer_id), None)
    if len(trades) <= 1:
        return trades[0] if trades else None
    live = [t for t in trades if t.status != FAILED_STATUS]
    if len(live) == 1:
        return live[0]
    if not live:
        return trades[-1]
    raise AmbiguousTradeError(f"{len(live)} live trades")


# Any: the seller document is a JSON object of scalars.
def _seller(trade: SkinTrade, wt: WaxpeerTrade) -> dict[str, Any]:
    """The stored seller with every non-empty value of ``wt``'s seller laid over it."""
    fresh = {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in wt.seller.model_dump().items()
        if value not in (None, "")
    }
    return {**(trade.seller or {}), **fresh}


def mirror(trade: SkinTrade, wt: WaxpeerTrade) -> None:
    """Copy one Waxpeer trade report onto our row; never blank a known value.

    ``status`` is always copied; ``accepted_at`` is stamped the first time a
    ``release_date`` appears (the buyer accepted the offer); ``is_released`` never goes
    back to false. The caller holds the order and the trade ``FOR UPDATE`` and commits.

    Args:
        trade: Our row, locked.
        wt: Waxpeer's report of the same trade.
    """
    at = now()
    trade.waxpeer_id = wt.id or trade.waxpeer_id
    trade.status = wt.status
    trade.trade_id = wt.trade_id or trade.trade_id
    trade.escrow_status = wt.escrow_status or trade.escrow_status
    trade.send_until = wt.send_until or trade.send_until
    if wt.release_date is not None and trade.accepted_at is None:
        trade.accepted_at = at
    trade.release_date = wt.release_date or trade.release_date
    trade.is_released = trade.is_released or wt.is_released
    trade.reason = wt.reason or trade.reason
    trade.penalties = wt.penalties or trade.penalties
    trade.seller = _seller(trade, wt)
    trade.last_polled_at = at
    trade.updated_at = at


__all__ = ["FAILED_STATUS", "AmbiguousTradeError", "mirror", "pick_trade"]
