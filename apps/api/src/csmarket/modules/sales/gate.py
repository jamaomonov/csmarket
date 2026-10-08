"""What every sell request checks first: the two switches, the trade link, the rate.

Both switches must be on — ``CSMARKET_SALES_ENABLED`` (with the Skinslink credentials,
``Settings.sales_active``) and the admin's «Выкуп включён» — else 409 ``sales_disabled``. The
trade link must be saved and not found bad (the check is advisory, as on the buy side). The
rate is the raw CBU rate (no uplift) less ``rate_cut_pct``.
"""

from __future__ import annotations

from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.core.errors import ConflictError, UpstreamUnavailableError, ValidationError
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.sales.pricing import sale_rate
from csmarket.modules.sales.rules import SaleSettings
from csmarket.modules.sales.settings_store import read_sale_settings
from csmarket.modules.users.api import TradeLink, User, parse_tradelink

#: Stored verdicts that refuse a link (as on the buy side: ``warn`` is a legacy trade hold).
_BAD_VERDICTS = frozenset({"bad", "warn"})


class RateUnavailableError(UpstreamUnavailableError):
    """No fresh CBU rate: nothing can be priced in soʻm.

    Twin of ``orders.checkout.RateUnavailableError`` (not exported by ``orders.api``).
    """

    status_code = 503
    type_uri = "https://csmarket.uz/errors/rate-unavailable"
    title = "Rate unavailable"


async def open_settings(db: AsyncSession, settings: Settings) -> SaleSettings:
    """The sale settings, if selling is on.

    Raises:
        ConflictError: ``sales_disabled`` — an env switch, a credential or the admin's switch
            is off.
    """
    doc = await read_sale_settings(db)
    if not settings.sales_active or not doc.enabled:
        raise ConflictError("selling is switched off", code="sales_disabled")
    return doc


def trade_link_of(user: User) -> TradeLink:
    """The seller's saved trade link, parsed.

    Twin of ``orders.checkout._gate_trade_link`` (private there; kept in step by hand).

    Raises:
        ConflictError: ``trade_link_missing``; ``trade_link_bad`` with ``reason``.
    """
    if not user.trade_link:
        raise ConflictError("add your Steam trade link first", code="trade_link_missing")
    if user.trade_link_verdict in _BAD_VERDICTS:
        reason = user.trade_link_reason or ("hold" if user.trade_link_verdict == "warn" else None)
        raise ConflictError(
            "this trade link cannot trade", code="trade_link_bad", reason=reason or "invalid"
        )
    try:
        return parse_tradelink(user.trade_link)
    except ValidationError as exc:
        raise ConflictError(
            "this trade link cannot trade", code="trade_link_bad", reason="invalid"
        ) from exc


async def sale_rate_now(
    db: AsyncSession, redis: Redis, settings: Settings, doc: SaleSettings
) -> Decimal:
    """The CBU rate (no uplift) less ``rate_cut_pct``.

    Raises:
        RateUnavailableError: No snapshot younger than ``fx_max_age_days``.
    """
    fx = await current_usd_uzs(
        db, redis, max_age_days=settings.fx_max_age_days, uplift_pct=Decimal(0)
    )
    if fx is None:
        raise RateUnavailableError("no soʻm rate", code="rate_unavailable")
    return sale_rate(fx.rate, doc)


__all__ = ["RateUnavailableError", "open_settings", "sale_rate_now", "trade_link_of"]
