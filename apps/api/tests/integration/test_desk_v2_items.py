"""«Мои сделки» v2, stage 2 (spec 2026-10-31-desk-v2): items after creation, part of the
skins, undo, traders, the guarantor."""

# ruff: noqa: F811  -- imported fixtures are requested by parameter name

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.desk_factory import (  # noqa: F401
    ASIIMOV,
    BASE,
    LINK,
    REDLINE,
    Headers,
    create,
    desk_headers,
    key,
    trader_inventory,
)
from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.sales_kit import use_client

pytestmark = pytest.mark.asyncio
PRICED = {"paid_amount": "1100", "paid_currency": "USD"}


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(
        inventory=[trader_inventory()], created=deposit("active"), status=deposit("active")
    )
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


def _stock(*prices: str) -> list[dict[str, str]]:
    return [
        {"name": f"S{n}", "skinslink_usd": p, "destination": "stock"} for n, p in enumerate(prices)
    ]


async def test_add_and_delete_items_recost_the_deal(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(
        integration_client, h, items=_stock("60"), paid_amount="90", paid_currency="USD"
    )
    url = f"{BASE}/deals/{deal['id']}/items"
    added = await integration_client.post(url, json={"items": _stock("30")}, headers=h | key())
    assert added.status_code == 200, added.text
    assert [i["cost_usd"] for i in added.json()["items"]] == ["60", "30"]
    first, second = (i["id"] for i in added.json()["items"])
    gone = await integration_client.delete(f"{BASE}/items/{second}", headers=h | key())
    assert gone.status_code == 200, gone.text
    assert [i["cost_usd"] for i in gone.json()["items"]] == ["90"]
    last = await integration_client.delete(f"{BASE}/items/{first}", headers=h | key())
    assert (last.status_code, last.json()["code"]) == (409, "last_item")
    missing = await integration_client.delete(f"{BASE}/items/{deal['id']}", headers=h | key())
    assert (missing.status_code, missing.json()["code"]) == (404, "item_not_found")


async def test_items_are_locked_once_one_is_resolved(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, items=_stock("60", "40"), **PRICED)
    a, b = (i["id"] for i in deal["items"])
    await integration_client.post(
        f"{BASE}/items/{a}/write-off", json={"note": "x"}, headers=h | key()
    )
    added = await integration_client.post(
        f"{BASE}/deals/{deal['id']}/items", json={"items": _stock("1")}, headers=h | key()
    )
    assert (added.status_code, added.json()["code"]) == (409, "price_locked")
    deleted = await integration_client.delete(f"{BASE}/items/{b}", headers=h | key())
    assert (deleted.status_code, deleted.json()["code"]) == (409, "price_locked")
    not_open = await integration_client.delete(f"{BASE}/items/{a}", headers=h | key())
    assert (not_open.status_code, not_open.json()["code"]) == (409, "item_not_open")


async def test_send_part_of_the_skins(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    redline, asiimov = (i["id"] for i in deal["items"])
    r = await integration_client.post(
        f"{BASE}/deals/{deal['id']}/deposit", json={"item_ids": [asiimov]}, headers=h | key()
    )
    assert r.status_code == 200, r.text
    assert fake.deposit_calls[0]["asset_ids"] == ["101"]
    assert [i["state"] for i in r.json()["items"]] == ["open", "sent"]
    fake.status = deposit("canceled")
    none = await integration_client.post(
        f"{BASE}/deals/{deal['id']}/deposit", json={"item_ids": [deal["id"]]}, headers=h | key()
    )
    assert (none.status_code, none.json()["code"]) == (409, "deposit_open")
    del redline


async def test_unknown_item_ids_send_nothing(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    r = await integration_client.post(
        f"{BASE}/deals/{deal['id']}/deposit", json={"item_ids": [deal["id"]]}, headers=h | key()
    )
    assert (r.status_code, r.json()["code"]) == (409, "nothing_to_send")
    assert fake.deposit_calls == []


async def test_undo_a_sale_and_a_write_off(
    integration_client: AsyncClient, db_session: AsyncSession, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, items=_stock("60", "40"), **PRICED)
    a, b = (i["id"] for i in deal["items"])
    await integration_client.post(
        f"{BASE}/items/{a}/sell",
        json={"where": "x", "amount": "700", "currency": "USD"},
        headers=h | key(),
    )
    closed = await integration_client.post(
        f"{BASE}/items/{b}/write-off", json={"note": "lost"}, headers=h | key()
    )
    assert closed.json()["status"] == "closed"
    undone = await integration_client.post(f"{BASE}/items/{a}/undo", headers=h | key())
    assert undone.status_code == 200, undone.text
    body = undone.json()
    assert (body["status"], body["profit_usd"]) == ("paid", "-440")
    item = body["items"][0]
    assert (item["state"], item["sold_usd"], item["sold_where"], item["resolved_at"]) == (
        "open",
        None,
        None,
        None,
    )
    off = (await integration_client.post(f"{BASE}/items/{b}/undo", headers=h | key())).json()
    assert (off["profit_usd"], off["items"][1]["note"]) == ("0", None)
    again = await integration_client.post(f"{BASE}/items/{b}/undo", headers=h | key())
    assert (again.status_code, again.json()["code"]) == (409, "item_not_undoable")
    audit = (
        await db_session.scalars(
            select(AdminAuditLog).where(AdminAuditLog.action == "desk.item.undo")
        )
    ).all()
    assert sorted(r.target_id for r in audit) == sorted([a, b])


async def test_a_credited_item_cannot_be_undone(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    fake.created = deposit("completed", amount_usd=Decimal(1200))
    await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    r = await integration_client.post(
        f"{BASE}/items/{deal['items'][0]['id']}/undo", headers=h | key()
    )
    assert (r.status_code, r.json()["code"]) == (409, "item_not_undoable")


async def test_traders_group_by_name(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    old = await create(integration_client, h, trader="Ali", items=_stock("10"), **PRICED)
    await integration_client.post(
        f"{BASE}/items/{old['items'][0]['id']}/sell",
        json={"where": "x", "amount": "1200", "currency": "USD"},
        headers=h | key(),
    )
    await create(
        integration_client, h, trader="ali ", trade_link=None, paid_amount="50", paid_currency="USD"
    )
    cancelled = await create(integration_client, h, trader="ALI", **PRICED)
    await integration_client.patch(
        f"{BASE}/deals/{cancelled['id']}", json={"status": "cancelled"}, headers=h | key()
    )
    await create(integration_client, h, trader="Bek")
    r = await integration_client.get(f"{BASE}/traders", params={"q": "al"}, headers=h)
    assert r.status_code == 200, r.text
    [ali] = r.json()["items"]
    assert (ali["deals"], ali["paid_usd"], ali["profit_usd"], ali["reverts"]) == (
        2,
        "1150",
        "100",
        0,
    )
    assert ali["trader"] == "ALI"
    assert ali["last_trade_link"] == LINK
    every = (await integration_client.get(f"{BASE}/traders", headers=h)).json()["items"]
    assert [t["trader"] for t in every] == ["Bek", "ALI"]


async def test_the_guarantor_is_kept(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, method="guarantor", guarantor="Гарант Саид")
    assert deal["guarantor"] == "Гарант Саид"
    url = f"{BASE}/deals/{deal['id']}"
    changed = await integration_client.patch(url, json={"guarantor": "Другой"}, headers=h | key())
    assert changed.json()["guarantor"] == "Другой"
    rows = (await integration_client.get(f"{BASE}/deals", headers=h)).json()["items"]
    assert rows[0]["guarantor"] == "Другой"
    cleared = await integration_client.patch(url, json={"guarantor": None}, headers=h | key())
    assert cleared.json()["guarantor"] is None
