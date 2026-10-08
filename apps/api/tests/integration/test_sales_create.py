# apps/api/tests/integration/test_sales_create.py
"""``POST /sell``: re-priced from the kept snapshot, stored before the one Skinslink call."""

# ruff: noqa: F811  -- the imported ``sales_on`` fixture is requested by parameter name

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from csmarket.modules.sales.models import PayoutCard, Sale, SaleItem
from csmarket.modules.skinslink.api import (
    Inventory,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)
from csmarket.modules.users.models import User
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.fake_deposit_client import FakeDepositClient, deposit, inv_item
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import HUMO, make_card
from tests.integration.sales_kit import (  # noqa: F401 -- the fixture
    Headers,
    ready_seller,
    sales_on,
    use_client,
)

pytestmark = pytest.mark.asyncio

URL = "/api/v1/sell"
TWO = Inventory(
    items=[inv_item("100", "12.45"), inv_item("101", "0.5", "P250 | Sand Dune (Field-Tested)")],
    max_items=50,
)
#: Skinslink's prices of TWO sum to 12.95 $; at the test rate: 149 600 + 5 600 = 155 200 soʻm.
BALANCE = {"asset_ids": ["100", "101"], "payout": {"to": "balance"}, "expected_payout_uzs": 158_300}


def _key(n: int = 1) -> dict[str, str]:
    return {"Idempotency-Key": f"test-sell-key-{n:08d}"}


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(
        inventory=[TWO], created=deposit("active", amount_usd=Decimal("12.95"))
    )
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def _seller(
    db: AsyncSession, client: AsyncClient, customer_headers: Headers
) -> dict[str, str]:
    """A ready seller whose inventory was read (the snapshot is kept)."""
    headers = await ready_seller(db, customer_headers)
    assert (await client.get("/api/v1/sell/inventory", headers=headers)).status_code == 200
    return headers


async def _sale(db: AsyncSession, number: str) -> Sale:
    sale = await db.scalar(
        select(Sale).where(Sale.number == number).execution_options(populate_existing=True)
    )
    assert sale is not None
    return sale


async def test_a_balance_sale_is_offered_with_the_payout_it_showed(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["payout_to"], body["payout_uzs"], body["bonus_uzs"]) == (
        "offered",
        "balance",
        "158300",
        "3100",
    )
    assert body["offer"] == {
        "url": "https://steamcommunity.com/tradeoffer/6912345678/",
        "bot_name": "Bot #3",
        "expires_at": "2026-10-08T12:30:00Z",
    }
    assert [(i["asset_id"], i["price_uzs"]) for i in body["items"]] == [
        ("100", "149600"),
        ("101", "5600"),
    ]
    sale = await _sale(db_session, body["number"])
    assert (sale.quoted_usd, sale.items_uzs, sale.margin_usd) == (
        Decimal("12.95"),
        Decimal(155_200),
        Decimal("0.6735"),
    )
    [call] = fake.deposit_calls
    assert (call["merchant_tx_id"], call["asset_ids"]) == (sale.id, ["100", "101"])


async def test_min_prices_are_99_percent_rounded_down(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert fake.deposit_calls[0]["min_prices"] == {
        "100": Decimal("12.325"),
        "101": Decimal("0.495"),
    }


async def test_a_replayed_key_answers_the_same_sale_and_calls_once(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    first = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    again = await integration_client.post(
        URL, json={**BALANCE, "asset_ids": ["100"]}, headers={**headers, **_key()}
    )
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["number"] == first.json()["number"]
    assert len(fake.deposit_calls) == 1


async def test_a_new_card_is_saved_encrypted_and_paid_to(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    body = {
        "asset_ids": ["100", "101"],
        "payout": {"to": "card", "new_card": {"type": "humo", "number": "9860 1234 5678 9015"}},
        "expected_payout_uzs": 147_400,
    }
    with capture_logs() as logs:
        r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert r.status_code == 201, r.text
    assert (r.json()["card"], r.json()["fee_uzs"]) == ({"type": "humo", "last4": "9015"}, "7800")
    assert HUMO not in r.text
    assert HUMO not in repr(logs)
    assert await db_session.scalar(select(func.count()).select_from(PayoutCard)) == 1


async def test_a_saved_card_of_someone_else_is_404(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    card = await make_card(db_session, await make_user(db_session))
    body = {**BALANCE, "payout": {"to": "card", "card_id": card.id}, "expected_payout_uzs": 147_400}
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert r.status_code == 404
    assert fake.deposit_calls == []


async def test_a_bad_card_number_is_422_without_echoing_it(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    bad = "9860123456789016"
    body = {
        **BALANCE,
        "payout": {"to": "card", "new_card": {"type": "humo", "number": bad}},
        "expected_payout_uzs": 147_400,
    }
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (422, "card_invalid")
    assert bad not in r.text


async def test_under_the_minimum_sum_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.inventories.clear()
    fake.inventories.append(
        Inventory(items=[inv_item("1", "0.4"), inv_item("2", "0.5")], max_items=50)
    )
    headers = await _seller(db_session, integration_client, customer_headers)
    body = {"asset_ids": ["1", "2"], "payout": {"to": "balance"}, "expected_payout_uzs": 10_200}
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"], r.json()["min_sum_uzs"]) == (
        409,
        "below_minimum",
        "12500",
    )
    assert await db_session.scalar(select(func.count()).select_from(Sale)) == 0


async def test_cheap_items_reaching_the_minimum_are_accepted(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.inventories.clear()
    fake.inventories.append(
        Inventory(items=[inv_item(str(n), "0.10") for n in range(11)], max_items=50)
    )
    headers = await _seller(db_session, integration_client, customer_headers)
    body = {
        "asset_ids": [str(n) for n in range(11)],
        "payout": {"to": "balance"},
        "expected_payout_uzs": 12_300,  # 11 × 1 100, +2 % = 12 342 → 12 300 (1.10 $)
    }
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert r.status_code == 201, r.text


async def test_exactly_one_dollar_is_under_the_minimum(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    """Skinslink refuses a deposit of exactly 1 $ (400 ``gt``, 2026-10-08)."""
    fake.inventories.clear()
    fake.inventories.append(
        Inventory(items=[inv_item(str(n), "0.10") for n in range(10)], max_items=50)
    )
    headers = await _seller(db_session, integration_client, customer_headers)
    body = {
        "asset_ids": [str(n) for n in range(10)],
        "payout": {"to": "balance"},
        "expected_payout_uzs": 11_200,
    }
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "below_minimum")
    assert fake.deposit_calls == []


async def test_a_card_payout_under_the_card_minimum_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.inventories.clear()
    fake.inventories.append(Inventory(items=[inv_item("1", "1.20")], max_items=50))
    headers = await _seller(db_session, integration_client, customer_headers)
    body = {
        "asset_ids": ["1"],
        "payout": {"to": "card", "new_card": {"type": "humo", "number": HUMO}},
        "expected_payout_uzs": 13_000,
    }
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"], r.json()["card_min_uzs"]) == (
        409,
        "below_card_minimum",
        "30000",
    )
    assert await db_session.scalar(select(func.count()).select_from(PayoutCard)) == 0


@pytest.mark.parametrize(
    "body",
    [
        {**BALANCE, "expected_payout_uzs": 158_400},  # the cart showed another figure
        {**BALANCE, "asset_ids": ["100", "999"]},  # not in the kept snapshot
    ],
)
@pytest.mark.usefixtures("sales_on")
async def test_a_moved_price_or_an_unknown_item_is_prices_changed(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    fake: FakeDepositClient,
    body: dict[str, object],
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "prices_changed")
    assert fake.deposit_calls == []


async def test_without_a_kept_snapshot_is_prices_changed(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)  # the inventory never read
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "prices_changed")


async def test_more_than_max_items_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.inventories.clear()
    fake.inventories.append(Inventory(items=TWO.items, max_items=1))
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"], r.json()["max_items"]) == (409, "too_many_items", 1)


async def test_skinslink_crediting_less_than_quoted_keeps_the_payout(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = deposit("active", amount_usd=Decimal("12.83"))  # above the 99 % floors
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["payout_uzs"]) == (201, "158300")
    sale = await _sale(db_session, r.json()["number"])
    assert (sale.quoted_usd, sale.amount_usd, sale.payout_uzs) == (
        Decimal("12.95"),
        Decimal("12.83"),
        Decimal(158_300),
    )


@pytest.mark.parametrize("code", ["item_specified_price_not_found", "inventory_reload"])
@pytest.mark.usefixtures("sales_on")
async def test_a_price_under_the_floor_is_prices_changed_and_closes_the_sale(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    fake: FakeDepositClient,
    code: str,
) -> None:
    fake.created = SkinslinkError("refused", status=400, code=code)
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "prices_changed")
    sale = await db_session.scalar(select(Sale).execution_options(populate_existing=True))
    assert sale is not None
    assert (sale.status, sale.fail_reason) == ("closed", code)
    calls = fake.inventory_calls
    await integration_client.get("/api/v1/sell/inventory", headers=headers)
    assert fake.inventory_calls == calls + 1  # the kept snapshot was dropped


async def test_a_steam_refusal_closes_the_sale_and_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = SkinslinkError("refused", status=400, code="profile_private")
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"], r.json()["reason"]) == (
        409,
        "steam_refused",
        "profile_private",
    )


async def test_a_used_tx_id_is_adopted_through_the_status(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = SkinslinkError("refused", status=409, code="already_exists")
    fake.status = deposit("active")
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["status"]) == (201, "offered")
    assert len(fake.status_calls) == 1


async def test_a_timeout_leaves_the_sale_creating_for_the_poll(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = SkinslinkUnavailableError("ReadTimeout")
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["status"], r.json()["offer"]) == (201, "creating", None)


async def test_a_forbidden_answer_closes_and_is_503(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = SkinslinkForbiddenError("forbidden", status=403)
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (503, "sales_unavailable")
    sale = await db_session.scalar(select(Sale).execution_options(populate_existing=True))
    assert sale is not None
    assert (sale.status, sale.fail_reason) == ("closed", "forbidden")


async def test_selling_off_stores_nothing(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)  # env switch off
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "sales_disabled")
    assert await db_session.scalar(select(func.count()).select_from(SaleItem)) == 0


async def test_without_a_key_is_422(
    integration_client: AsyncClient, customer_headers: Headers, sales_on: None
) -> None:
    r = await integration_client.post(URL, json=BALANCE, headers=await customer_headers())
    assert r.status_code == 422


async def test_skinslinks_too_many_items_reports_the_snapshots_max_and_closes(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    fake.created = SkinslinkError("refused", status=400, code="too_many_items")
    headers = await _seller(db_session, integration_client, customer_headers)
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"], r.json()["max_items"]) == (409, "too_many_items", 50)
    sale = await db_session.scalar(select(Sale).execution_options(populate_existing=True))
    assert sale is not None
    assert (sale.status, sale.fail_reason) == ("closed", "too_many_items")


async def test_the_sale_is_committed_before_the_one_skinslink_call(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    seen: list[str | None] = []
    original = fake.create_deposit

    async def spy(**kwargs: object) -> object:
        # a separate connection sees the sale only if it is committed
        row = await db_session.scalar(select(Sale.status).execution_options(populate_existing=True))
        seen.append(row)
        return await original(**kwargs)  # type: ignore[arg-type]

    fake.create_deposit = spy  # type: ignore[method-assign,assignment]
    headers = await _seller(db_session, integration_client, customer_headers)
    await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert seen == ["creating"]


@pytest.mark.parametrize(
    "payout",
    [
        {"to": "card", "new_card": {"type": "humo", "number": HUMO}, "card_id": None},
        {"to": "balance", "new_card": {"type": "humo", "number": HUMO}},
    ],
)
async def test_a_malformed_body_never_echoes_the_card_number(
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    payout: dict[str, object],
) -> None:
    # no expected_payout_uzs, and (second case) a balance payout that carries a card
    body = {"asset_ids": ["100"], "payout": payout}
    r = await integration_client.post(
        URL, json=body, headers={**await customer_headers(), **_key()}
    )
    assert r.status_code == 422
    assert HUMO not in r.text
    assert all("input" not in e and "ctx" not in e for e in r.json()["detail"])


async def test_a_card_number_of_the_wrong_length_is_not_echoed(
    integration_client: AsyncClient, customer_headers: Headers, sales_on: None
) -> None:
    long = HUMO * 3
    body = {
        **BALANCE,
        "payout": {"to": "card", "new_card": {"type": "humo", "number": long}},
    }
    r = await integration_client.post(
        URL, json=body, headers={**await customer_headers(), **_key()}
    )
    assert r.status_code == 422
    assert HUMO not in r.text


async def test_a_fourth_card_is_409_and_stores_no_sale(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers = await _seller(db_session, integration_client, customer_headers)
    user = await db_session.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    for _ in range(3):
        await make_card(db_session, user)
    body = {
        **BALANCE,
        "payout": {"to": "card", "new_card": {"type": "humo", "number": HUMO}},
        "expected_payout_uzs": 147_400,
    }
    r = await integration_client.post(URL, json=body, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "cards_limit")
    assert await db_session.scalar(select(func.count()).select_from(Sale)) == 0
    assert fake.deposit_calls == []
