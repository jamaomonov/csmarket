"""The Central Bank of Uzbekistan's official USD rate (spec §9: the sell rate).

One public, keyless JSON endpoint. Anything that is not one plausible USD row is an
error — a wrong rate prices the whole catalogue, so we refuse rather than guess.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

from csmarket.core.logging import get_logger

log = get_logger("csmarket.fx.cbu")

#: Soʻm per dollar outside this band is a parsing error, not a market move.
_PLAUSIBLE = (Decimal(1000), Decimal(100000))


class CbuError(Exception):
    """The CBU answer was missing, unreachable or implausible."""


async def fetch_usd_uzs(
    *, url: str, timeout: float, client: httpx.AsyncClient | None = None
) -> Decimal:
    """Soʻm per one US dollar, as the CBU publishes it today.

    Args:
        url: The CBU USD endpoint.
        timeout: Request timeout in seconds.
        client: An existing client to reuse; one is opened per call otherwise.

    Returns:
        The rate, quantised to four decimals.

    Raises:
        CbuError: Network failure, HTTP error, or an answer that is not one plausible USD row.
    """
    try:
        if client is not None:
            resp = await client.get(url, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as own:
                resp = await own.get(url)
    except httpx.HTTPError as exc:
        log.warning("fx.cbu.network_error", error=type(exc).__name__)
        raise CbuError(type(exc).__name__) from exc
    if resp.status_code != 200:
        raise CbuError(f"status {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise CbuError("not json") from exc
    if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], dict):
        raise CbuError("unexpected shape")
    row = body[0]
    if row.get("Ccy") != "USD":
        raise CbuError("not the USD row")
    try:
        rate = Decimal(str(row["Rate"])) / Decimal(str(row.get("Nominal") or "1"))
    except (KeyError, InvalidOperation, ZeroDivisionError) as exc:
        raise CbuError("bad rate") from exc
    if not _PLAUSIBLE[0] <= rate <= _PLAUSIBLE[1]:
        raise CbuError("implausible rate")
    return rate.quantize(Decimal("0.0001"))
