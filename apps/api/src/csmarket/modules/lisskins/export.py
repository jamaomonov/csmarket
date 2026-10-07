"""LIS-SKINS' public price export, read as a stream (spec 2026-10-07 §3).

``GET <lisskins_export_url>`` (no key) is one JSON object —
``{"status": "success", "last_update": <unix>, "items": [ … ]}``, ~855 MB, ~2.4 M lots — so
it is never in memory whole: each element of ``items`` becomes a :class:`Lot` as soon as it
is complete and goes to ``on_lot``, if it is one we sell (``delivery_type`` 1, not
trade-locked, a usable id, name and price).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

import httpx

from csmarket.core.json_stream import ItemsScanner
from csmarket.core.metrics import record_lisskins_call
from csmarket.modules.lisskins.client import LisskinsUnavailableError
from csmarket.modules.lisskins.values import decimal_of, int_of, str_of

STATUS_SUCCESS = re.compile(r'"status"\s*:\s*"success"')
LAST_UPDATE = re.compile(r'"last_update"\s*:\s*([0-9]+)')
#: ``delivery_type`` of a lot LIS-SKINS' own bot sends at once (2 = the seller, ≤ 12 h).
INSTANT = 1
#: The export's CDN answered the 2026-10-07 probe only with a browser-like agent.
USER_AGENT = "Mozilla/5.0 (compatible; csmarket.uz)"
_UNIT = Decimal(1)
_FLOAT_PLACES = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Sticker:
    """A sticker on a lot, as LIS-SKINS names it."""

    name: str
    image: str | None
    slot: int | None
    wear: float | None


@dataclass(frozen=True, slots=True)
class Lot:
    """One instant, unlocked lot of the export, in units (1000 = $1)."""

    id: int
    name: str
    price_units: int
    paint_index: int | None
    float_value: Decimal | None
    paint_seed: int | None
    #: The Steam asset — the same asset on Skinslink is shown once (``skins.merge_offers``).
    asset_id: str | None
    inspect_url: str | None
    stickers: tuple[Sticker, ...]


class ExportReader(Protocol):
    """:func:`read_export`'s shape (the snapshot tests pass a scripted one)."""

    async def __call__(
        self, url: str, on_lot: Callable[[Lot], None], *, timeout_seconds: float
    ) -> int:
        """Feed every sellable lot to ``on_lot``; return ``last_update``."""
        ...


def to_units(price_usd: Decimal) -> int:
    """USD as units (1000 = $1), half up."""
    return int((price_usd * 1000).quantize(_UNIT, rounding=ROUND_HALF_UP))


def _float(value: object) -> Decimal | None:
    number = decimal_of(value)
    if number is None or not Decimal(0) <= number <= Decimal(1):
        return None
    return number.quantize(_FLOAT_PLACES)


def _stickers(value: object) -> tuple[Sticker, ...]:
    found: list[Sticker] = []
    for raw in value if isinstance(value, list) else []:
        name = str_of(raw.get("name")) if isinstance(raw, Mapping) else None
        if name is None or not isinstance(raw, Mapping):
            continue
        wear = decimal_of(raw.get("wear"))
        found.append(
            Sticker(
                name=name,
                image=str_of(raw.get("image")),
                slot=int_of(raw.get("slot")),
                wear=None if wear is None else float(wear),
            )
        )
    return tuple(found)


#: ``lisskins_offers.asset_id`` is ``VARCHAR(32)``; ``paint_seed`` an ``INTEGER``.
_ASSET_ID_MAX = 32
_SEED_MAX = 2**31 - 1


def _fitting(asset_id: str | None) -> str | None:
    """An asset id that fits its column; a longer one is dropped, never the lot."""
    return asset_id if asset_id is not None and len(asset_id) <= _ASSET_ID_MAX else None


def _bounded(seed: int | None) -> int | None:
    """A paint seed that fits ``INTEGER``, else ``None``."""
    return seed if seed is not None and 0 <= seed <= _SEED_MAX else None


# Any: one lot object of the export, read field by field.
def lot_of(raw: Mapping[str, Any]) -> Lot | None:
    """A lot we may sell, or ``None``: slow delivery, trade-locked, or unusable."""
    if raw.get("delivery_type") != INSTANT or raw.get("unlock_at") is not None:
        return None
    lot_id, name, price = (
        int_of(raw.get("id")),
        str_of(raw.get("name")),
        decimal_of(raw.get("price")),
    )
    if lot_id is None or name is None or price is None or price <= 0:
        return None
    link = raw.get("item_link")
    return Lot(
        id=lot_id,
        name=name,
        price_units=to_units(price),
        paint_index=int_of(raw.get("item_paint_index")),
        float_value=_float(raw.get("item_float")),
        paint_seed=_bounded(int_of(raw.get("item_paint_seed"))),
        asset_id=_fitting(str_of(raw.get("item_asset_id"))),
        inspect_url=link if isinstance(link, str) and link.startswith("steam://") else None,
        stickers=_stickers(raw.get("stickers")),
    )


@asynccontextmanager
async def _session(
    client: httpx.AsyncClient | None, timeout_seconds: float
) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(timeout=timeout_seconds) as fresh:
        yield fresh


def _unavailable(reason: str) -> LisskinsUnavailableError:
    record_lisskins_call("export", "unavailable")
    return LisskinsUnavailableError(reason)


async def read_export(
    url: str,
    on_lot: Callable[[Lot], None],
    *,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Stream the export; ``on_lot`` gets every sellable lot, in order.

    Returns:
        The export's ``last_update`` (unix seconds).

    Raises:
        LisskinsUnavailableError: Transport, a non-200, a body that is not the export, one
            cut short, or one that does not say ``"status": "success"`` — never read as an
            empty market.
    """
    scanner = ItemsScanner(success=STATUS_SUCCESS, cursor=LAST_UPDATE)
    try:
        async with (
            _session(client, timeout_seconds) as http,
            http.stream("GET", url, headers={"User-Agent": USER_AGENT}) as resp,
        ):
            if resp.status_code != 200:
                raise _unavailable(f"http {resp.status_code}")
            async for text in resp.aiter_text():
                for raw in scanner.feed(text):
                    if isinstance(raw, Mapping) and (lot := lot_of(raw)) is not None:
                        on_lot(lot)
        last = scanner.finish()
    except httpx.HTTPError as exc:
        raise _unavailable(type(exc).__name__) from exc
    except ValueError as exc:  # not the export, cut short, or not a success
        raise _unavailable("unexpected body") from exc
    if last is None:
        raise _unavailable("no last_update")
    record_lisskins_call("export", "ok")
    return int(last)


__all__ = ["INSTANT", "ExportReader", "Lot", "Sticker", "lot_of", "read_export", "to_units"]
