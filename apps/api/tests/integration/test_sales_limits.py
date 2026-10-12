"""What ``POST /sell`` refuses before it stores a sale (review 2026-10-11 SB-6, SB-10):
a blocked seller, an item already in an open sale, the admin's USD ceilings."""

# ruff: noqa: F811  -- the imported ``sales_on`` fixture is requested by parameter name

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.core.errors import ConflictError
from csmarket.modules.sales.limits import check_sale_allowed
from csmarket.modules.sales.models import Sale, SaleBlock
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS
from csmarket.modules.skinslink.api import Inventory
from csmarket.modules.users.models import User
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.fake_deposit_client import FakeDepositClient, deposit, inv_item
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import enable_sales, make_sale
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
#: 12.95 $ of items, 158 300 soʻm to the balance at the test rate (see test_sales_create).
BALANCE = {"asset_ids": ["100", "101"], "payout": {"to": "balance"}, "expected_payout_uzs": 158_300}


def _key(n: int = 1) -> dict[str, str]:
    return {"Idempotency-Key": f"test-limit-key-{n:08d}"}


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(
        inventory=[TWO], created=deposit("active", amount_usd=Decimal("12.95"))
    )
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def _seller(
    db: AsyncSession, client: AsyncClient, customer_headers: Headers, **settings: object
) -> tuple[dict[str, str], User]:
    headers = await ready_seller(db, customer_headers)
    if settings:
        await enable_sales(db, **settings)
    assert (await client.get("/api/v1/sell/inventory", headers=headers)).status_code == 200
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return headers, user


async def _sales(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(Sale)) or 0)


async def test_a_blocked_seller_is_409_and_nothing_is_stored(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers, user = await _seller(db_session, integration_client, customer_headers)
    db_session.add(SaleBlock(user_id=user.id, reason="chargeback"))
    await db_session.commit()
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "sell_blocked")
    assert "chargeback" not in r.text
    assert await _sales(db_session) == 0
    assert fake.deposit_calls == []


async def test_an_item_in_an_open_sale_cannot_be_sold_again(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers, _ = await _seller(db_session, integration_client, customer_headers)
    first = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key(1)})
    assert first.status_code == 201
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key(2)})
    assert (r.status_code, r.json()["code"]) == (409, "items_in_sale")
    assert await _sales(db_session) == 1
    assert len(fake.deposit_calls) == 1


async def test_an_item_of_a_closed_sale_can_be_sold_again(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers, user = await _seller(db_session, integration_client, customer_headers)
    await make_sale(db_session, user=user, status="closed")
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert r.status_code == 201, r.text


async def test_above_the_sale_maximum_is_409_with_the_limit(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers, _ = await _seller(
        db_session, integration_client, customer_headers, max_sale_usd=Decimal("10")
    )
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    body = r.json()
    assert (r.status_code, body["code"], body["limit_usd"], body["left_usd"]) == (
        409,
        "above_sale_maximum",
        "10",
        "10",
    )
    assert await _sales(db_session) == 0


async def test_the_sellers_daily_limit_counts_the_last_24_hours(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers, user = await _seller(
        db_session, integration_client, customer_headers, max_user_day_usd=Decimal("20")
    )
    held = (("200", "Knife", Decimal("8"), Decimal(90_000)),)
    await make_sale(db_session, user=user, status="hold", items=held)  # counts
    await make_sale(db_session, user=user, status="closed", items=held)  # paid nothing
    await make_sale(
        db_session, user=user, status="credited", items=held, created_at=now() - timedelta(hours=25)
    )
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    body = r.json()
    assert (r.status_code, body["code"], body["limit_usd"], body["left_usd"]) == (
        409,
        "user_daily_limit",
        "20",
        "12",
    )


async def test_under_the_limits_the_sale_goes_through(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers, _ = await _seller(
        db_session,
        integration_client,
        customer_headers,
        max_sale_usd=Decimal("13"),
        max_user_day_usd=Decimal("13"),
        max_day_usd=Decimal("13"),
    )
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    assert r.status_code == 201, r.text


async def test_the_shops_daily_limit_counts_every_seller(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,
    fake: FakeDepositClient,
) -> None:
    headers, _ = await _seller(
        db_session, integration_client, customer_headers, max_day_usd=Decimal("15")
    )
    await make_sale(db_session, status="payout", payout_to="card")  # someone else's 12.95 $
    r = await integration_client.post(URL, json=BALANCE, headers={**headers, **_key()})
    body = r.json()
    assert (r.status_code, body["code"], body["left_usd"]) == (409, "daily_limit", "2.05")


async def test_an_old_settings_row_without_the_limits_reads_as_no_limit(
    db_session: AsyncSession,
) -> None:
    raw = DEFAULT_SALE_SETTINGS.model_dump(mode="json")
    for name in ("max_sale_usd", "max_user_day_usd", "max_day_usd"):
        raw.pop(name)
    doc = type(DEFAULT_SALE_SETTINGS).model_validate(raw)
    assert (doc.max_sale_usd, doc.max_user_day_usd, doc.max_day_usd) == (None, None, None)


async def test_two_sales_at_once_cannot_both_pass_the_daily_limit(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """The shop's lock holds until the sale is committed: the second waits and sees it."""
    doc = DEFAULT_SALE_SETTINGS.model_copy(update={"max_day_usd": Decimal("20")})
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    a, b = await make_user(db_session), await make_user(db_session)
    async with factory() as first, factory() as second:
        await check_sale_allowed(
            first, user_id=a.id, asset_ids=["1"], quoted_usd=Decimal(12), doc=doc, at=now()
        )
        waiting = asyncio.create_task(
            check_sale_allowed(
                second, user_id=b.id, asset_ids=["2"], quoted_usd=Decimal(12), doc=doc, at=now()
            )
        )
        await asyncio.sleep(0.3)
        assert not waiting.done()
        await make_sale(db_session, user=a, status="offered")  # what `first` would store
        await first.commit()
        with pytest.raises(ConflictError, match="daily limit"):
            await waiting
        await second.rollback()
