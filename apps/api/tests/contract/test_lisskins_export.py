"""The public export (respx): only instant, unlocked lots; ``last_update``; a cut, failed or
foreign body is an outage, never an empty market."""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.lisskins.api import LisskinsUnavailableError, Lot, read_export

URL = "https://lis-skins.com/market_export_json/api_csgo_full.json"
LOT = {
    "id": 9001,
    "name": "AK-47 | Redline (Field-Tested)",
    "price": 12.35,
    "unlock_at": None,
    "item_class_id": "1",
    "created_at": "2026-10-07T10:00:00.000000Z",
    "item_float": "0.2512345678",
    "name_tag": None,
    "item_paint_index": 282,
    "item_paint_seed": 661,
    "item_asset_id": "38000000001",
    "item_link": "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20S1A2D3",
    "stickers": [
        {
            "name": "Sticker | Crown (Foil)",
            "image": "https://steamcdn-a.akamaihd.net/x.png",
            "wear": 0,
            "slot": 1,
        },
        "junk",
    ],
    "delivery_type": 1,
}


def _body(items: Sequence[object], status: str = "success") -> str:
    return json.dumps({"status": status, "last_update": 1759831200, "items": items})


async def _read(body: str | httpx.Response) -> tuple[int, list[Lot]]:
    respx.get(URL).mock(
        return_value=body if isinstance(body, httpx.Response) else httpx.Response(200, text=body)
    )
    got: list[Lot] = []
    last = await read_export(URL, got.append, timeout_seconds=1)
    return last, got


@respx.mock
async def test_only_instant_unlocked_priced_lots_are_kept() -> None:
    items = [
        LOT,
        {**LOT, "id": 9002, "delivery_type": 2},
        {**LOT, "id": 9003, "unlock_at": "2026-10-10T10:00:00.000000Z"},
        {**LOT, "id": 9004, "price": 0},
        {**LOT, "id": "nope"},
    ]
    last, got = await _read(_body(items))
    assert last == 1759831200
    assert [lot.id for lot in got] == [9001]
    lot = got[0]
    assert (lot.price_units, lot.paint_index, lot.paint_seed, lot.asset_id) == (
        12_350,
        282,
        661,
        "38000000001",
    )
    assert lot.float_value == Decimal("0.251235")
    assert lot.inspect_url is not None
    assert lot.inspect_url.startswith("steam://")
    assert [(s.name, s.slot, s.wear) for s in lot.stickers] == [("Sticker | Crown (Foil)", 1, 0.0)]


@respx.mock
async def test_the_export_is_asked_with_a_browser_agent() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, text=_body([LOT])))
    await read_export(URL, lambda _lot: None, timeout_seconds=1)
    assert route.calls.last.request.headers["User-Agent"].startswith("Mozilla/5.0")


@respx.mock
@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, text=_body([LOT, LOT])[:-40]),  # cut inside the array
        httpx.Response(200, text=_body([LOT], status="error")),
        httpx.Response(200, text="<html>maintenance</html>"),
        httpx.Response(503, text="busy"),
    ],
)
async def test_a_cut_failed_or_foreign_body_is_unavailable(answer: httpx.Response) -> None:
    with pytest.raises(LisskinsUnavailableError):
        await _read(answer)


@respx.mock
async def test_a_transport_failure_is_unavailable() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(LisskinsUnavailableError):
        await read_export(URL, lambda _lot: None, timeout_seconds=1)
