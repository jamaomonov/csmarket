"""Skinslink merchant API (respx): catalogue, events, purchase, status, balance.

Shapes from https://docs.skinslink.com/llm (2026-10-06). Every partner, token and asset id
is made up.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.skinslink.api import (
    CatalogueItem,
    Purchase,
    SkinslinkClient,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkRateLimitedError,
    SkinslinkUnavailableError,
)
from csmarket.modules.skinslink.stream import ItemsScanner

BASE = "https://api.skinslink.com/api/v1"
PARTNER = 39734273
TOKEN = "AbCdEf12"


def _client() -> SkinslinkClient:
    return SkinslinkClient(api_key="k", base_url=BASE, timeout_seconds=1)


def _ok(data: object) -> dict[str, object]:
    return {"success": True, "message": "ok", "data": data}


ITEM: dict[str, object] = {
    "id": "38029384123",
    "name": "AK-47 | Redline (Field-Tested)",
    "price": 12.45,
    "image_url": "https://community.cloudflare.steamstatic.com/economy/image/x",
    "exterior": "Field-Tested",
    "float": 0.2512,
    "paint_seed": 661,
    "inspect_url": "steam://rungame/730/x",
    "phase": None,
}


async def _buy(client: SkinslinkClient | None = None) -> Purchase:
    return await (client or _client()).purchase(
        asset_id="38029384123",
        partner=PARTNER,
        token=TOKEN,
        merchant_tx_id="order-1",
        max_price_usd=Decimal("46.00"),
    )


async def _batches(
    client: SkinslinkClient, *, size: int = 1000
) -> tuple[list[list[CatalogueItem]], str]:
    got: list[list[CatalogueItem]] = []

    async def keep(batch: list[CatalogueItem]) -> None:
        got.append(batch)

    cursor = await client.available_batches(keep, batch_size=size)
    return got, cursor


@respx.mock
async def test_available_streams_items_in_batches_and_reads_the_cursor_after_them() -> None:
    items = [{**ITEM, "id": str(n)} for n in range(5)]
    route = respx.get(f"{BASE}/merchant/purchase/available").mock(
        return_value=httpx.Response(
            200,
            json=_ok(
                {
                    "game": "csgo",
                    "total": 5,
                    "items": items,
                    "last_update_at": "2026-10-06T10:00:00Z",
                }
            ),
        )
    )
    got, cursor = await _batches(_client(), size=2)
    request = route.calls.last.request
    assert request.headers["X-Api-Key"] == "k"
    assert request.url.params["full"] == "true"
    assert request.url.params["extended"] == "true"
    assert request.url.params["game"] == "csgo"
    assert cursor == "2026-10-06T10:00:00Z"
    assert [[i.id for i in b] for b in got] == [["0", "1"], ["2", "3"], ["4"]]
    item = got[0][0]
    assert (item.price_usd, item.float_value, item.paint_seed, item.inspect_url) == (
        Decimal("12.45"),
        0.2512,
        661,
        "steam://rungame/730/x",
    )


@pytest.mark.parametrize("chunk", [1, 7, 64, 100_000])
def test_the_items_scanner_reads_any_chunking(chunk: int) -> None:
    body = json.dumps(
        _ok(
            {
                "game": "csgo",
                "items": [ITEM, {"id": "2", "name": "a, ] {x}", "price": 1.5}],
                "last_update_at": "c9",
            }
        )
    )
    scanner = ItemsScanner()
    found: list[object] = []
    for start in range(0, len(body), chunk):
        found += scanner.feed(body[start : start + chunk])
    assert [o["id"] for o in found if isinstance(o, dict)] == ["38029384123", "2"]
    assert scanner.finish() == "c9"


@respx.mock
async def test_available_drops_unreadable_items() -> None:
    bad = [{"id": "1", "name": "x", "price": 0}, {"name": "no id", "price": 1}, {"id": "2"}]
    respx.get(f"{BASE}/merchant/purchase/available").mock(
        return_value=httpx.Response(200, json=_ok({"items": [ITEM, *bad], "last_update_at": "c"}))
    )
    got, _ = await _batches(_client())
    assert [i.id for b in got for i in b] == ["38029384123"]


@respx.mock
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (
            httpx.Response(200, content=b'{"success":true,"data":{"items":[{"id":"1"'),
            SkinslinkUnavailableError,
        ),
        (httpx.Response(200, json={"success": False, "message": "no"}), SkinslinkError),
        (httpx.Response(403, json={"success": False}), SkinslinkForbiddenError),
        (httpx.Response(503, text="down"), SkinslinkUnavailableError),
    ],
)
async def test_a_bad_full_load_raises(response: httpx.Response, error: type[Exception]) -> None:
    respx.get(f"{BASE}/merchant/purchase/available").mock(return_value=response)
    with pytest.raises(error):
        await _batches(_client())


@respx.mock
async def test_events_keep_the_cursor_verbatim_and_read_upsert_and_remove() -> None:
    respx.get(f"{BASE}/merchant/purchase/events").mock(
        return_value=httpx.Response(
            200,
            json=_ok(
                {
                    "since": "2026-10-06T10:00:00Z",
                    "next": "2026-10-06T10:00:12.512434831Z",
                    "count": 2,
                    "more": True,
                    "reset": False,
                    "events": [
                        {
                            "type": "upsert",
                            "at": "2026-10-06T10:00:11Z",
                            "game": "csgo",
                            "id": ITEM["id"],
                            "item": ITEM,
                        },
                        {"type": "remove", "at": "2026-10-06T10:00:12Z", "game": "csgo", "id": "1"},
                    ],
                }
            ),
        )
    )
    page = await _client().events("2026-10-06T10:00:00Z")
    assert page.next == "2026-10-06T10:00:12.512434831Z"
    assert page.more is True
    assert page.reset is False
    assert [e.type for e in page.events] == ["upsert", "remove"]
    assert page.events[0].item is not None
    assert page.events[1].item is None


@respx.mock
async def test_events_reset_has_no_events() -> None:
    respx.get(f"{BASE}/merchant/purchase/events").mock(
        return_value=httpx.Response(
            200,
            json=_ok(
                {"since": "x", "next": "y", "count": 0, "more": False, "reset": True, "events": []}
            ),
        )
    )
    page = await _client().events("x")
    assert page.reset is True
    assert page.events == []


@respx.mock
async def test_purchase_posts_json_and_parses_the_answer() -> None:
    route = respx.post(f"{BASE}/merchant/purchase").mock(
        return_value=httpx.Response(
            200,
            json=_ok(
                {
                    "id": 178,
                    "merchant_tx_id": "order-1",
                    "status": "pending",
                    "steam_id": "76561190000000001",
                    "amount": 45.99,
                    "date": "2026-10-06T10:30:00Z",
                    "item": {"id": "38029384123", "name": "x", "price": 45.99},
                }
            ),
        )
    )
    p = await _buy()
    sent = json.loads(route.calls.last.request.read())
    assert sent == {
        "game": "csgo",
        "asset_id": "38029384123",
        "partner": PARTNER,
        "token": TOKEN,
        "merchant_tx_id": "order-1",
        "max_price": 46.0,
    }
    assert (p.id, p.status, p.amount_usd, p.asset_id) == (
        178,
        "pending",
        Decimal("45.99"),
        "38029384123",
    )
    assert p.offer_id is None
    assert p.fail_reason is None


@respx.mock
async def test_purchase_failed_answer_carries_the_reason() -> None:
    respx.post(f"{BASE}/merchant/purchase").mock(
        return_value=httpx.Response(
            200,
            json=_ok(
                {
                    "id": 179,
                    "status": "failed",
                    "fail_reason": "item_sold",
                    "amount": 1.0,
                    "date": "x",
                }
            ),
        )
    )
    p = await _buy()
    assert p.status == "failed"
    assert p.fail_reason == "item_sold"


@respx.mock
async def test_validation_error_exposes_the_domain_code() -> None:
    respx.post(f"{BASE}/merchant/purchase").mock(
        return_value=httpx.Response(
            400,
            json={
                "success": False,
                "message": "validation error",
                "data": [{"field": "partner", "code": "trade_banned", "message": "x"}],
            },
        )
    )
    with pytest.raises(SkinslinkError) as exc:
        await _buy()
    assert exc.value.status == 400
    assert exc.value.code == "trade_banned"


@respx.mock
async def test_duplicate_is_409() -> None:
    respx.post(f"{BASE}/merchant/purchase").mock(
        return_value=httpx.Response(409, json={"success": False, "message": "duplicate"})
    )
    with pytest.raises(SkinslinkError) as exc:
        await _buy()
    assert exc.value.status == 409


@respx.mock
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (403, SkinslinkForbiddenError),
        (429, SkinslinkRateLimitedError),
        (500, SkinslinkUnavailableError),
        (502, SkinslinkUnavailableError),
        (408, SkinslinkUnavailableError),
    ],
)
async def test_http_statuses_map_to_errors(status: int, error: type[Exception]) -> None:
    respx.get(f"{BASE}/merchant/balance").mock(
        return_value=httpx.Response(status, json={"success": False, "message": "x"})
    )
    with pytest.raises(error):
        await _client().balance()


@respx.mock
async def test_transport_failure_and_garbage_are_unavailable() -> None:
    respx.get(f"{BASE}/merchant/balance").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(SkinslinkUnavailableError):
        await _client().balance()
    respx.post(f"{BASE}/merchant/purchase").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(SkinslinkUnavailableError):
        await _buy()


@respx.mock
async def test_status_404_is_none_and_balance_parses() -> None:
    respx.get(f"{BASE}/merchant/purchase/status").mock(
        return_value=httpx.Response(404, json={"success": False, "message": "not found"})
    )
    assert await _client().purchase_status(merchant_tx_id="nope") is None
    respx.get(f"{BASE}/merchant/balance").mock(
        return_value=httpx.Response(
            200, json=_ok({"total": 1250.75, "hold": 320.5, "available": 930.25})
        )
    )
    b = await _client().balance()
    assert (b.total, b.hold, b.available) == (
        Decimal("1250.75"),
        Decimal("320.5"),
        Decimal("930.25"),
    )


@respx.mock
async def test_status_reads_the_offer_and_hold() -> None:
    respx.get(f"{BASE}/merchant/purchase/status").mock(
        return_value=httpx.Response(
            200,
            json=_ok(
                {
                    "id": 178,
                    "merchant_tx_id": "order-1",
                    "status": "hold",
                    "trade_offer_id": "6912345678",
                    "hold_end_date": "2026-10-13T00:00:00Z",
                    "amount": 45.99,
                }
            ),
        )
    )
    p = await _client().purchase_status(merchant_tx_id="order-1")
    assert p is not None
    assert (p.status, p.offer_id, p.hold_end_date) == ("hold", "6912345678", "2026-10-13T00:00:00Z")


async def test_no_key_is_unavailable_without_a_call() -> None:
    with pytest.raises(SkinslinkUnavailableError):
        await SkinslinkClient(api_key="", base_url=BASE, timeout_seconds=1).balance()


@respx.mock
@pytest.mark.parametrize(
    ("cap", "sent_cap"), [("12.3549", 12.354), ("12.354", 12.354), ("9.1", 9.1)]
)
async def test_max_price_never_rounds_above_the_cap(cap: str, sent_cap: float) -> None:
    route = respx.post(f"{BASE}/merchant/purchase").mock(
        return_value=httpx.Response(
            200, json=_ok({"id": 1, "merchant_tx_id": "o", "status": "pending"})
        )
    )
    await _client().purchase(
        asset_id="1", partner=PARTNER, token=TOKEN, merchant_tx_id="o", max_price_usd=Decimal(cap)
    )
    assert json.loads(route.calls.last.request.read())["max_price"] == sent_cap


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"success": True, "data": {"note": "no items here"}}),
        httpx.Response(200, content=b"x" * 70_000),
        httpx.Response(200, content=b'{"success":false,"data":{"items":[]}}'),
    ],
)
async def test_a_body_without_a_readable_list_is_unavailable(response: httpx.Response) -> None:
    respx.get(f"{BASE}/merchant/purchase/available").mock(return_value=response)
    with pytest.raises(SkinslinkUnavailableError):
        await _batches(_client())


@respx.mock
async def test_a_transport_error_is_unavailable() -> None:
    respx.get(f"{BASE}/merchant/purchase/available").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(SkinslinkUnavailableError):
        await _batches(_client())


async def test_no_key_never_calls() -> None:
    client = SkinslinkClient(api_key="", base_url=BASE, timeout_seconds=1)
    with pytest.raises(SkinslinkUnavailableError):
        await _batches(client)


@respx.mock
async def test_a_list_without_a_cursor_starts_from_now() -> None:
    respx.get(f"{BASE}/merchant/purchase/available").mock(
        return_value=httpx.Response(200, json=_ok({"items": [ITEM]}))
    )
    got, cursor = await _batches(_client())
    assert [i.id for b in got for i in b] == ["38029384123"]
    assert cursor.startswith("20")
