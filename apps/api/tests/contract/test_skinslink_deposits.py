# apps/api/tests/contract/test_skinslink_deposits.py
"""Skinslink deposit API (respx): inventory, create-deposit, deposit status, every refusal.

Shapes from the Skinslink docs saved on 2026-10-08 (get-inventory, create-deposit,
deposit-status, errors). Every partner, token, asset id and Steam id is made up.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.skinslink.api import (
    STEAM_ACCOUNT_CODES,
    Deposit,
    InventoryItem,
    SkinslinkDepositClient,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)

BASE = "https://api.skinslink.com/api/v1"
PARTNER = 39734273
TOKEN = "AbCdEf12"

ITEM = {
    "id": "38029384123",
    "name": "AK-47 | Redline (Field-Tested)",
    "price": 12.45,
    "image_url": "https://community.cloudflare.steamstatic.com/economy/image/x",
    "exterior": "Field-Tested",
    "rarity": "Classified",
    "rarity_color": "#d32ce6",
}
INVENTORY = {
    "items": [ITEM, {"id": "1", "name": "Free", "price": 0}, {"name": "No id", "price": 1}],
    "total": 47,
    "sum": 284.9,
    "game": "csgo",
    "max_items": 50,
}
DEPOSIT = {
    "id": 42,
    "merchant_tx_id": "sale-1",
    "status": "active",
    "amount": 36.25,
    "bot_name": "Skinslink Bot #3",
    "bot_steam_id": 76561190000000003,
    "trade_offer_id": "6912345678",
    "trade_offer_expiry_at": "2026-02-16T12:30:00Z",
}


def _client() -> SkinslinkDepositClient:
    return SkinslinkDepositClient(api_key="k", base_url=BASE, timeout_seconds=1)


def _ok(data: object) -> dict[str, object]:
    return {"success": True, "message": "ok", "data": data}


def _no(message: str, data: object = None, *, status: int = 400) -> httpx.Response:
    body: dict[str, object] = {"success": False, "message": message}
    if data is not None:
        body["data"] = data
    return httpx.Response(status, json=body)


def _field(code: str, field: str = "partner") -> list[dict[str, str]]:
    return [{"field": field, "code": code, "message": "x"}]


async def _create(min_prices: dict[str, Decimal] | None = None) -> Deposit:
    return await _client().create_deposit(
        merchant_tx_id="sale-1",
        partner=PARTNER,
        token=TOKEN,
        asset_ids=["38029384123"],
        min_prices=min_prices or {"38029384123": Decimal("12.3255")},
    )


@respx.mock
async def test_inventory_reads_the_priced_items_and_max_items() -> None:
    route = respx.post(f"{BASE}/merchant/inventory").mock(
        return_value=httpx.Response(200, json=_ok(INVENTORY))
    )
    inv = await _client().inventory(partner=PARTNER, token=TOKEN)
    assert inv.max_items == 50
    assert inv.items == [
        InventoryItem(
            id="38029384123",
            name="AK-47 | Redline (Field-Tested)",
            price_usd=Decimal("12.45"),
            image_url="https://community.cloudflare.steamstatic.com/economy/image/x",
            exterior="Field-Tested",
            rarity="Classified",
            rarity_color="#d32ce6",
        )
    ]
    request = route.calls.last.request
    assert json.loads(request.content) == {"game": "csgo", "partner": PARTNER, "token": TOKEN}
    assert request.headers["X-Api-Key"] == "k"


@respx.mock
async def test_inventory_without_max_items_is_unavailable() -> None:
    body = {k: v for k, v in INVENTORY.items() if k != "max_items"}
    respx.post(f"{BASE}/merchant/inventory").mock(return_value=httpx.Response(200, json=_ok(body)))
    with pytest.raises(SkinslinkUnavailableError):
        await _client().inventory(partner=PARTNER, token=TOKEN)


@pytest.mark.parametrize("code", sorted(STEAM_ACCOUNT_CODES))
@respx.mock
async def test_inventory_steam_account_refusals_carry_their_code(code: str) -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(
        return_value=_no("validation error", _field(code))
    )
    with pytest.raises(SkinslinkError) as caught:
        await _client().inventory(partner=PARTNER, token=TOKEN)
    assert (caught.value.status, caught.value.code) == (400, code)


@respx.mock
async def test_inventory_reload_is_a_refusal_with_its_code() -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(
        return_value=_no("validation error", _field("inventory_reload", "inventory"))
    )
    with pytest.raises(SkinslinkError) as caught:
        await _client().inventory(partner=PARTNER, token=TOKEN)
    assert caught.value.code == "inventory_reload"


@pytest.mark.parametrize("status", [408, 500, 502])
@respx.mock
async def test_inventory_timeouts_and_5xx_are_unavailable(status: int) -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(return_value=_no("timeout error", status=status))
    with pytest.raises(SkinslinkUnavailableError):
        await _client().inventory(partner=PARTNER, token=TOKEN)


@respx.mock
async def test_inventory_403_is_forbidden() -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(
        return_value=_no("IP not whitelisted: 203.0.113.42", status=403)
    )
    with pytest.raises(SkinslinkForbiddenError):
        await _client().inventory(partner=PARTNER, token=TOKEN)


@respx.mock
async def test_a_transport_error_is_unavailable() -> None:
    respx.post(f"{BASE}/merchant/inventory").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(SkinslinkUnavailableError):
        await _client().inventory(partner=PARTNER, token=TOKEN)


@respx.mock
async def test_create_deposit_sends_floors_rounded_down_and_reads_the_offer() -> None:
    route = respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=httpx.Response(200, json=_ok(DEPOSIT))
    )
    deposit = await _create({"38029384123": Decimal("12.3259")})
    assert deposit == Deposit(
        id=42,
        merchant_tx_id="sale-1",
        status="active",
        amount_usd=Decimal("36.25"),
        bot_name="Skinslink Bot #3",
        trade_offer_id="6912345678",
        offer_expiry_at="2026-02-16T12:30:00Z",
        hold_end_date=None,
        fail_reason=None,
    )
    assert json.loads(route.calls.last.request.content) == {
        "merchant_tx_id": "sale-1",
        "game": "csgo",
        "partner": PARTNER,
        "token": TOKEN,
        "asset_ids": ["38029384123"],
        "min_prices": {"38029384123": 12.325},
    }


@respx.mock
async def test_a_price_under_the_floor_is_item_specified_price_not_found() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("item_specified_price_not_found")
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert (caught.value.status, caught.value.code) == (400, "item_specified_price_not_found")


@respx.mock
async def test_a_stale_snapshot_on_create_is_inventory_reload() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("validation error", _field("inventory_reload", "inventory"))
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert caught.value.code == "inventory_reload"


@respx.mock
async def test_a_used_merchant_tx_id_is_409_already_exists() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("already exist error", status=409)
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert (caught.value.status, caught.value.code) == (409, "already_exists")


@respx.mock
async def test_too_many_items_is_its_own_code() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("deposit exceeds the maximum of 50 items per deposit")
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert caught.value.code == "too_many_items"


@respx.mock
async def test_a_steam_refusal_on_create_carries_its_code() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(
        return_value=_no("validation error", _field("trade_banned"))
    )
    with pytest.raises(SkinslinkError) as caught:
        await _create()
    assert caught.value.code == "trade_banned"


@respx.mock
async def test_a_5xx_on_create_is_unavailable_the_deposit_may_exist() -> None:
    respx.post(f"{BASE}/merchant/create-deposit").mock(return_value=_no("internal", status=500))
    with pytest.raises(SkinslinkUnavailableError):
        await _create()


@respx.mock
async def test_status_is_asked_by_merchant_tx_id_and_reads_hold() -> None:
    body = {**DEPOSIT, "status": "hold", "hold_end_date": "2026-10-15T10:00:00Z"}
    del body["amount"]
    route = respx.get(f"{BASE}/merchant/deposit/status").mock(
        return_value=httpx.Response(200, json=_ok(body))
    )
    deposit = await _client().deposit_status(merchant_tx_id="sale-1")
    assert deposit is not None
    assert (deposit.status, deposit.hold_end_date, deposit.amount_usd) == (
        "hold",
        "2026-10-15T10:00:00Z",
        None,
    )
    assert route.calls.last.request.url.params["merchant_tx_id"] == "sale-1"


@respx.mock
async def test_status_reads_the_fail_reason() -> None:
    body = {**DEPOSIT, "status": "reverted", "fail_reason": "user_reverted"}
    respx.get(f"{BASE}/merchant/deposit/status").mock(
        return_value=httpx.Response(200, json=_ok(body))
    )
    deposit = await _client().deposit_status(merchant_tx_id="sale-1")
    assert deposit is not None
    assert (deposit.status, deposit.fail_reason) == ("reverted", "user_reverted")


@respx.mock
async def test_an_unknown_deposit_is_none() -> None:
    respx.get(f"{BASE}/merchant/deposit/status").mock(
        return_value=_no("not found error", status=404)
    )
    assert await _client().deposit_status(merchant_tx_id="sale-1") is None


@respx.mock
async def test_a_status_without_an_id_is_unavailable() -> None:
    respx.get(f"{BASE}/merchant/deposit/status").mock(
        return_value=httpx.Response(200, json=_ok({"status": "hold"}))
    )
    with pytest.raises(SkinslinkUnavailableError):
        await _client().deposit_status(merchant_tx_id="sale-1")
