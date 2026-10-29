"""The fallback USD/UZS rate: open.er-api.com's daily market mid-rate.

cbu.uz refuses our EU server (seen 2026-10-22); this source is reachable and stays within a
fraction of a percent of the CBU rate. It is asked only when the CBU fails and the newest
rate is old (``fx.service.refresh_with_fallback``); its snapshots are ``source='er-api'``.
The same plausibility band as the CBU: a wrong rate prices the whole catalogue.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

from csmarket.modules.fx.cbu import PLAUSIBLE, CbuError


async def fetch_fallback_usd_uzs(
    *, url: str, timeout: float, client: httpx.AsyncClient | None = None
) -> Decimal:
    """Soʻm per dollar from the fallback source, to 4 places.

    Raises:
        CbuError: A network failure, a non-200, or anything but one plausible UZS rate.
    """
    try:
        if client is not None:
            resp = await client.get(url, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as own:
                resp = await own.get(url)
    except httpx.HTTPError as exc:
        raise CbuError(type(exc).__name__) from exc
    if resp.status_code != 200:
        raise CbuError(f"status {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise CbuError("not json") from exc
    if not isinstance(body, dict) or body.get("result") != "success":
        raise CbuError("unexpected shape")
    rates = body.get("rates")
    raw = rates.get("UZS") if isinstance(rates, dict) else None
    try:
        rate = Decimal(str(raw))
    except InvalidOperation as exc:
        raise CbuError("bad rate") from exc
    if not rate.is_finite() or not PLAUSIBLE[0] <= rate <= PLAUSIBLE[1]:
        raise CbuError("implausible rate")
    return rate.quantize(Decimal("0.0001"))


__all__ = ["fetch_fallback_usd_uzs"]
