"""The seller's sales: newest first, one by number, the sum on its way to the balance."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.sales.views import list_sales
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import credit_sale
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import ITEMS, make_request, make_sale

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]


async def _me(db: AsyncSession, customer_headers: Headers) -> tuple[dict[str, str], User]:
    headers = await customer_headers()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return headers, user


async def test_my_sales_newest_first_without_the_ones_refused_at_once(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    old = await make_sale(db_session, user=me, created_at=now() - timedelta(hours=2))
    await make_sale(db_session, user=me, status="closed", trade_id=None, fail_reason="trade_banned")
    new = await make_sale(db_session, user=me, status="hold", trade_id=7)
    await make_sale(db_session)  # someone else's
    r = await integration_client.get("/api/v1/sales", headers=headers)
    assert r.status_code == 200
    assert [s["number"] for s in r.json()["items"]] == [new.number, old.number]
    assert r.json()["next_cursor"] is None


async def test_pages_of_twenty(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    for n in range(21):
        await make_sale(db_session, user=me, created_at=now() - timedelta(minutes=n))
    first = (await integration_client.get("/api/v1/sales", headers=headers)).json()
    assert len(first["items"]) == 20
    assert first["next_cursor"]
    rest = await integration_client.get(
        "/api/v1/sales", params={"cursor": first["next_cursor"]}, headers=headers
    )
    assert len(rest.json()["items"]) == 1
    assert rest.json()["next_cursor"] is None
    bad = await integration_client.get("/api/v1/sales", params={"cursor": "x"}, headers=headers)
    assert (bad.status_code, bad.json()["code"]) == (422, "cursor")


async def test_only_my_held_sales_with_the_status_filter_and_its_cursor(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    held = [
        await make_sale(db_session, user=me, status="hold", created_at=now() - timedelta(minutes=n))
        for n in range(21)
    ]
    await make_sale(db_session, user=me, status="offered")
    await make_sale(db_session, user=me, status="credited")
    await make_sale(db_session, status="hold")  # someone else's
    first = await integration_client.get("/api/v1/sales?status=hold", headers=headers)
    assert first.status_code == 200, first.text
    page = first.json()
    assert [s["number"] for s in page["items"]] == [s.number for s in held[:20]]
    rest = await integration_client.get(
        "/api/v1/sales", params={"status": "hold", "cursor": page["next_cursor"]}, headers=headers
    )
    assert [s["number"] for s in rest.json()["items"]] == [held[20].number]
    assert rest.json()["next_cursor"] is None
    bad = await integration_client.get("/api/v1/sales?status=offered", headers=headers)
    assert bad.status_code == 422


async def test_sale_items_carry_the_catalogue_exterior_and_rarity_colour(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    await _catalogue(db_session, ITEMS[0][1], phases=("", "Phase 2"))
    sale = await make_sale(db_session, user=me)
    r = await integration_client.get(f"/api/v1/sales/{sale.number}", headers=headers)
    looks = {i["name"]: (i["exterior"], i["rarity_color"]) for i in r.json()["items"]}
    assert looks == {ITEMS[0][1]: ("FT", "#d32ce6"), ITEMS[1][1]: (None, None)}
    [listed] = (await integration_client.get("/api/v1/sales", headers=headers)).json()["items"]
    assert listed["items"][0]["exterior"] == "FT"


async def _catalogue(db: AsyncSession, name: str, *, phases: tuple[str, ...]) -> None:
    db.add_all(
        SkinItem(
            id=new_id(),
            market_hash_name=name,
            phase=phase,
            slug=f"{name}-{phase}-{new_id()[:6]}".lower().replace(" ", "-"),
            category="rifles",
            search_text=name.lower(),
            exterior="FT",
            rarity_color="#d32ce6",
        )
        for phase in phases
    )
    await db.commit()


async def test_a_page_costs_the_same_queries_for_any_number_of_sales(
    db_session: AsyncSession,
) -> None:
    async def _queries(count: int) -> int:
        user = await make_user(db_session)
        await _catalogue(db_session, f"Item {count}", phases=("",))
        for n in range(count):
            sale = await make_sale(
                db_session,
                user=user,
                payout_to="card" if n % 2 else "balance",
                status="payout",
                items=((str(n), f"Item {count}", Decimal(1), Decimal(12_700)), *ITEMS),
            )
            if n % 2:
                await make_request(db_session, sale)
        statements: list[str] = []

        def _capture(*args: object) -> None:
            statements.append(str(args[2]))

        engine = db_session.bind.sync_engine  # type: ignore[union-attr]
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            rows, _ = await list_sales(db_session, user.id, None)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        assert len(rows) == count
        return len(statements)

    assert await _queries(2) == await _queries(10) > 0


async def test_one_sale_by_number_and_nobody_elses(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    mine = await make_sale(db_session, user=me, payout_to="card", status="payout")
    await make_request(db_session, mine, status="to_pay")
    r = await integration_client.get(f"/api/v1/sales/{mine.number}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert (body["payout_status"], body["card"]["last4"], body["offer"]) == ("to_pay", "9015", None)
    other = await make_sale(db_session)
    for number in (other.number, "S0000000", "nope", mine.number.lower()):
        r = await integration_client.get(f"/api/v1/sales/{number}", headers=headers)
        assert r.status_code == 404, number


async def test_the_offer_shows_only_while_offered_and_the_money_date_while_held(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    offered = await make_sale(db_session, user=me, status="offered", bot_name="Bot #3")
    held = await make_sale(
        db_session, user=me, status="hold", hold_end_at=now() + timedelta(days=7)
    )
    a = (await integration_client.get(f"/api/v1/sales/{offered.number}", headers=headers)).json()
    b = (await integration_client.get(f"/api/v1/sales/{held.number}", headers=headers)).json()
    assert a["offer"]["url"] == "https://steamcommunity.com/tradeoffer/6912345678/"
    assert (a["money_at"], b["offer"]) == (None, None)
    assert b["money_at"] is not None


async def test_pending_is_the_held_balance_sales(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    await make_sale(db_session, user=me, status="hold", payout_uzs=Decimal(158_300))
    await make_sale(db_session, user=me, status="hold", payout_uzs=Decimal(10_200))
    await make_sale(db_session, user=me, status="hold", payout_to="card")
    await make_sale(db_session, user=me, status="offered", payout_uzs=Decimal(99_900))
    await make_sale(db_session, status="hold")  # someone else's
    r = await integration_client.get("/api/v1/sales/pending", headers=headers)
    assert (r.status_code, r.json()) == (200, {"pending_uzs": "168500"})


async def test_a_sale_credit_shows_in_the_balance_history_with_its_number(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    sale = await make_sale(db_session, user=me, status="credited", payout_uzs=Decimal(158_300))
    await credit_sale(db_session, user_id=me.id, sale_id=sale.id, amount=Decimal(158_300))
    await db_session.commit()
    r = await integration_client.get("/api/v1/wallet/entries", headers=headers)
    [entry] = r.json()["items"]
    assert (entry["kind"], entry["amount_uzs"], entry["reference_number"]) == (
        "sale_credit",
        "+158300",
        sale.number,
    )


async def test_signed_out_is_401(integration_client: AsyncClient) -> None:
    for url in ("/api/v1/sales", "/api/v1/sales/pending", "/api/v1/sales/S0000000"):
        assert (await integration_client.get(url)).status_code == 401


async def test_a_rejected_payout_shows_its_reason_to_the_seller_only_then(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    rejected = await make_sale(db_session, user=me, payout_to="card", status="payout")
    await make_request(db_session, rejected, status="rejected", reject_reason="Карта заблокирована")
    paying = await make_sale(db_session, user=me, payout_to="card", status="payout")
    await make_request(db_session, paying, status="to_pay", reject_reason="stale")
    got = await integration_client.get(f"/api/v1/sales/{rejected.number}", headers=headers)
    assert (got.json()["payout_status"], got.json()["payout_reject_reason"]) == (
        "rejected",
        "Карта заблокирована",
    )
    other = await integration_client.get(f"/api/v1/sales/{paying.number}", headers=headers)
    assert other.json()["payout_reject_reason"] is None
