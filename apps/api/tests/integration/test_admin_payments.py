"""Admin payments API: search, detail with the kassas' transactions (M3 Task 10)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.click.models import ClickTransaction
from csmarket.modules.payme.models import PaymeTransaction
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.users.models import User
from csmarket.modules.uzum.models import UzumTransaction
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.orders_factory import make_order
from tests.integration.payments_factory import make_user

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/payments"
T0 = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
#: Payer's phone as Uzum may send it — it must never reach an admin response.
FULL_PHONE = "998901234567"


async def _topup(
    db: AsyncSession, user: User, number: str, *, status: str = "pending", amount: int = 50000
) -> WalletTopup:
    topup = WalletTopup(
        id=new_id(),
        number=number,
        user_id=user.id,
        amount_uzs=Decimal(amount),
        status=status,
        idempotency_key=f"seed-{uuid.uuid4()}",
        expires_at=T0 + timedelta(minutes=30),
        succeeded_at=T0 if status == "succeeded" else None,
    )
    db.add(topup)
    await db.commit()
    return topup


async def _payment(
    db: AsyncSession,
    topup: WalletTopup,
    *,
    provider: str = "click",
    status: str = "created",
    minutes: int = 0,
    provider_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Payment:
    payment = Payment(
        id=new_id(),
        number=topup.number,
        purpose="topup",
        topup_id=topup.id,
        user_id=topup.user_id,
        provider=provider,
        provider_ref=provider_ref,
        amount_uzs=topup.amount_uzs,
        status=status,
        extra_metadata=metadata or {},
        created_at=T0 + timedelta(minutes=minutes),
        updated_at=T0 + timedelta(minutes=minutes),
        succeeded_at=T0 + timedelta(minutes=minutes + 1) if status == "succeeded" else None,
    )
    db.add(payment)
    await db.commit()
    return payment


async def _named_user(db: AsyncSession, name: str) -> User:
    user = await make_user(db)
    user.display_name = name
    await db.commit()
    return user


# --- the gate ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["", "/{id}"])
async def test_a_customer_is_403_and_anonymous_401(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    path: str,
) -> None:
    user = await make_user(db_session)
    payment = await _payment(db_session, await _topup(db_session, user, "T7KQ4M2X"))
    url = BASE + path.format(id=payment.id)
    assert (await integration_client.get(url, headers=await customer_headers())).status_code == 403
    assert (await integration_client.get(url)).status_code == 401


# --- list -------------------------------------------------------------------------------


async def test_list_row_shape_and_newest_first(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    alice = await _named_user(db_session, "Alice")
    topup = await _topup(db_session, alice, "T7KQ4M2X", amount=120000)
    older = await _payment(db_session, topup, provider="payme", minutes=0)
    newer = await _payment(db_session, topup, provider="click", status="succeeded", minutes=5)

    r = await integration_client.get(BASE, headers=await admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["id"] for p in body["items"]] == [newer.id, older.id]
    assert body["next_cursor"] is None
    row = body["items"][0]
    assert row == {
        "id": newer.id,
        "number": "T7KQ4M2X",
        "purpose": "topup",
        "provider": "click",
        "amount_uzs": "120000",
        "status": "succeeded",
        "created_at": "2026-09-30T10:05:00Z",
        "succeeded_at": "2026-09-30T10:06:00Z",
        "user": {"id": alice.id, "display_name": "Alice"},
    }
    assert body["items"][1]["succeeded_at"] is None


async def test_number_search_is_a_case_insensitive_prefix_match(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    mine = await _topup(db_session, user, "T7KQ4M2X")
    other = await _topup(db_session, user, "T9ZZ0000")
    first = await _payment(db_session, mine, provider="click", minutes=0)
    second = await _payment(db_session, mine, provider="uzum", minutes=1)
    await _payment(db_session, other, minutes=2)
    h = await admin_headers()

    for q in ("T7K", "t7k", " t7kq4m2x "):
        r = await integration_client.get(BASE, params={"q": q}, headers=h)
        assert [p["id"] for p in r.json()["items"]] == [second.id, first.id], q
    r = await integration_client.get(BASE, params={"q": "7KQ"}, headers=h)
    assert r.json()["items"] == []  # a prefix, not a substring
    r = await integration_client.get(BASE, params={"q": "T%"}, headers=h)
    assert r.json()["items"] == []  # ``%`` is literal
    r = await integration_client.get(BASE, params={"q": "  "}, headers=h)
    assert len(r.json()["items"]) == 3  # blank = no filter


async def test_list_filters_by_status_provider_and_purpose(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    topup = await _topup(db_session, user, "T7KQ4M2X")
    click_ok = await _payment(db_session, topup, provider="click", status="succeeded", minutes=0)
    payme_failed = await _payment(db_session, topup, provider="payme", status="failed", minutes=1)
    uzum_ok = await _payment(db_session, topup, provider="uzum", status="succeeded", minutes=2)
    h = await admin_headers()

    async def ids(**params: str) -> list[str]:
        r = await integration_client.get(BASE, params=params, headers=h)
        assert r.status_code == 200, r.text
        return [p["id"] for p in r.json()["items"]]

    assert await ids(status="succeeded") == [uzum_ok.id, click_ok.id]
    assert await ids(status="failed") == [payme_failed.id]
    assert await ids(provider="payme") == [payme_failed.id]
    assert await ids(provider="click", status="succeeded") == [click_ok.id]
    assert await ids(provider="payme", status="succeeded") == []
    assert len(await ids(purpose="topup")) == 3
    assert await ids(purpose="order") == []


@pytest.mark.parametrize(
    "params",
    [
        {"status": "weird"},
        {"provider": "paypal"},
        {"purpose": "gift"},
        {"limit": 0},
        {"limit": 101},
        {"cursor": "%%%nope"},
        {"q": "T7K\x00"},  # Postgres refuses NUL in a text parameter: 422, never a 500
    ],
)
async def test_list_refuses_bad_params(
    integration_client: AsyncClient, admin_headers: Headers, params: dict[str, str | int]
) -> None:
    r = await integration_client.get(BASE, params=params, headers=await admin_headers())
    assert r.status_code == 422, r.text


async def test_list_pages_without_gaps_or_duplicates(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    topup = await _topup(db_session, user, "T7KQ4M2X")
    for i in range(7):
        # Two attempts share a timestamp: the id tie-break must keep them apart.
        await _payment(db_session, topup, minutes=i // 2)
    h = await admin_headers()
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 3}
        if cursor is not None:
            params["cursor"] = cursor
        page = (await integration_client.get(BASE, params=params, headers=h)).json()
        seen.extend(p["id"] for p in page["items"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert len(seen) == len(set(seen)) == 7


async def test_list_query_count_is_constant(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    h = await admin_headers()

    async def _count(attempts: int) -> int:
        for i in range(attempts):
            user = await make_user(db_session)
            topup = await _topup(db_session, user, f"T{uuid.uuid4().hex[:7].upper()}")
            await _payment(db_session, topup, minutes=i)
        statements: list[str] = []

        def _capture(*args: object) -> None:
            statements.append(str(args[2]))

        engine = db_engine.sync_engine
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            r = await integration_client.get(BASE, params={"limit": 100}, headers=h)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        assert r.status_code == 200
        return len(statements)

    few = await _count(3)
    assert few > 0
    assert few == await _count(15)


# --- detail -----------------------------------------------------------------------------


async def test_detail_unknown_or_malformed_id_is_404(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    for ident in (str(uuid.uuid4()), "not-a-uuid"):
        r = await integration_client.get(f"{BASE}/{ident}", headers=h)
        assert r.status_code == 404, r.text


async def test_detail_without_a_kassa_row(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await _named_user(db_session, "Alice")
    topup = await _topup(db_session, user, "T7KQ4M2X", status="succeeded", amount=80000)
    payment = await _payment(
        db_session,
        topup,
        provider="mock",
        status="succeeded",
        provider_ref="mock:T7KQ4M2X",
        metadata={"settle_event_id": "mock:T7KQ4M2X", "nested": {"x": 1}, "n": 3},
    )
    topup.payment_id = payment.id
    await db_session.commit()

    r = await integration_client.get(f"{BASE}/{payment.id}", headers=await admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"payment", "topup", "order", "kassa"}
    assert body["order"] is None
    assert body["payment"]["id"] == payment.id
    assert body["payment"]["provider_ref"] == "mock:T7KQ4M2X"
    assert body["payment"]["user"] == {"id": user.id, "display_name": "Alice"}
    # Metadata keeps scalars only.
    assert body["payment"]["metadata"] == {"settle_event_id": "mock:T7KQ4M2X", "n": 3}
    assert body["topup"] == {
        "number": "T7KQ4M2X",
        "amount_uzs": "80000",
        "status": "succeeded",
        "expires_at": "2026-09-30T10:30:00Z",
        "succeeded_at": "2026-09-30T10:00:00Z",
    }
    assert body["kassa"] == []


async def test_detail_shows_each_kassas_transactions(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    topup = await _topup(db_session, user, "T7KQ4M2X", amount=50000)
    click_p = await _payment(db_session, topup, provider="click", status="succeeded", minutes=0)
    payme_p = await _payment(db_session, topup, provider="payme", status="pending", minutes=1)
    uzum_p = await _payment(db_session, topup, provider="uzum", status="failed", minutes=2)
    db_session.add_all(
        [
            ClickTransaction(
                id=new_id(),
                click_trans_id=1234567890,
                service_id=111,
                payment_id=click_p.id,
                account="T7KQ4M2X",
                amount=Decimal(50000),
                status="CONFIRMED",
                click_paydoc_id=99887766,
                prepare_time=T0 + timedelta(seconds=5),
                complete_time=T0 + timedelta(seconds=40),
                created_at=T0,
                updated_at=T0,
            ),
            PaymeTransaction(
                id=new_id(),
                payme_id="64f0c0ffee0123456789abcd",
                payment_id=payme_p.id,
                account="T7KQ4M2X",
                amount_tiyin=5000000,
                state=-2,
                reason=5,
                create_time=1_790_000_000_000,
                perform_time=1_790_000_060_000,
                cancel_time=1_790_000_120_000,
                fiscal_data={"PERFORM": {"receipt_id": "r-1", "qr": "secret-looking"}},
                created_at=T0,
                updated_at=T0,
            ),
            UzumTransaction(
                id=new_id(),
                trans_id="uzum-trans-0001",
                payment_id=uzum_p.id,
                account="T7KQ4M2X",
                amount_tiyin=5000000,
                status="REVERSED",
                service_id=555,
                create_time=1_790_000_000_000,
                confirm_time=1_790_000_050_000,
                reverse_time=1_790_000_090_000,
                payment_source={"paymentSource": "UZCARD", "phone": FULL_PHONE, "tariff": "x"},
                created_at=T0,
                updated_at=T0,
            ),
        ]
    )
    await db_session.commit()
    h = await admin_headers()

    click = (await integration_client.get(f"{BASE}/{click_p.id}", headers=h)).json()["kassa"]
    assert click == [
        {
            "provider": "click",
            "external_id": "1234567890",
            "status": "CONFIRMED",
            "amount": "50000",
            "amount_unit": "soum",
            "times": {
                "created": "2026-09-30T10:00:05Z",
                "performed": "2026-09-30T10:00:40Z",
                "cancelled": None,
            },
            "extra": {"account": "T7KQ4M2X", "click_paydoc_id": "99887766", "service_id": "111"},
        }
    ]

    payme = (await integration_client.get(f"{BASE}/{payme_p.id}", headers=h)).json()
    assert payme["kassa"] == [
        {
            "provider": "payme",
            "external_id": "64f0c0ffee0123456789abcd",
            "status": "cancelled_after_perform",
            "amount": "5000000",
            "amount_unit": "tiyin",
            "times": {
                "created": datetime.fromtimestamp(1_790_000_000, UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                "performed": datetime.fromtimestamp(1_790_000_060, UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                "cancelled": datetime.fromtimestamp(1_790_000_120, UTC)
                .isoformat()
                .replace("+00:00", "Z"),
            },
            "extra": {"account": "T7KQ4M2X", "reason": "5"},
        }
    ]
    assert "secret-looking" not in json.dumps(payme)  # fiscal receipts stay out

    uzum = (await integration_client.get(f"{BASE}/{uzum_p.id}", headers=h)).json()["kassa"]
    assert len(uzum) == 1
    assert uzum[0]["provider"] == "uzum"
    assert uzum[0]["external_id"] == "uzum-trans-0001"
    assert uzum[0]["status"] == "REVERSED"
    assert uzum[0]["amount"] == "5000000"
    assert uzum[0]["amount_unit"] == "tiyin"
    assert uzum[0]["times"]["cancelled"] is not None
    assert uzum[0]["extra"]["service_id"] == "555"


async def test_unset_kassa_times_are_null(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    topup = await _topup(db_session, user, "T7KQ4M2X")
    payme_p = await _payment(db_session, topup, provider="payme", status="pending")
    uzum_p = await _payment(db_session, topup, provider="uzum", status="pending", minutes=1)
    db_session.add_all(
        [
            PaymeTransaction(
                id=new_id(),
                payme_id="p-created",
                payment_id=payme_p.id,
                account="T7KQ4M2X",
                amount_tiyin=5000000,
                state=1,
                create_time=1_790_000_000_000,
                perform_time=0,
                cancel_time=0,
                created_at=T0,
                updated_at=T0,
            ),
            UzumTransaction(
                id=new_id(),
                trans_id="u-created",
                payment_id=uzum_p.id,
                account="T7KQ4M2X",
                amount_tiyin=5000000,
                status="CREATED",
                create_time=0,
                created_at=T0,
                updated_at=T0,
            ),
        ]
    )
    await db_session.commit()
    h = await admin_headers()
    payme = (await integration_client.get(f"{BASE}/{payme_p.id}", headers=h)).json()["kassa"][0]
    assert payme["status"] == "created"
    assert payme["times"]["performed"] is None
    assert payme["times"]["cancelled"] is None
    assert payme["extra"] == {"account": "T7KQ4M2X"}  # no reason
    uzum = (await integration_client.get(f"{BASE}/{uzum_p.id}", headers=h)).json()["kassa"][0]
    assert uzum["times"] == {
        "created": "2026-09-30T10:00:00Z",  # unset create_time falls back to the row's
        "performed": None,
        "cancelled": None,
    }
    assert uzum["extra"] == {"account": "T7KQ4M2X"}  # service_id unset


@pytest.mark.parametrize(
    ("source", "phone"),
    [
        ({"paymentSource": "UZCARD", "phone": FULL_PHONE}, "+998••••••67"),
        ({"paymentSource": "HUMO", "phone": "+" + FULL_PHONE}, "+998••••••67"),
        ({"paymentSource": "HUMO", "phone": "90 123-45-67"}, "••••••67"),
        ({"paymentSource": "HUMO", "phone": "12"}, "••••••"),
        ({"paymentSource": "HUMO", "phone": 998901234567}, "+998••••••67"),
        ({"paymentSource": "HUMO", "phone": None}, None),
        ({"paymentSource": "HUMO", "phone": {"n": FULL_PHONE}}, None),
        ({"paymentSource": "HUMO", "phone": True}, None),
        ({"paymentSource": "HUMO"}, None),
        ({"paymentSource": {"a": 1}, "phone": FULL_PHONE}, "+998••••••67"),
        ({"tariff": "x", "cardNumber": "8600123412341234"}, None),
        ({}, None),
    ],
)
async def test_uzum_payment_source_is_reduced_to_source_and_a_masked_phone(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    source: dict[str, Any],
    phone: str | None,
) -> None:
    user = await make_user(db_session)
    topup = await _topup(db_session, user, "T7KQ4M2X")
    payment = await _payment(db_session, topup, provider="uzum", status="succeeded")
    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="uzum-mask",
            payment_id=payment.id,
            account="T7KQ4M2X",
            amount_tiyin=5000000,
            status="CONFIRMED",
            create_time=1_790_000_000_000,
            payment_source=source,
            created_at=T0,
            updated_at=T0,
        )
    )
    await db_session.commit()

    r = await integration_client.get(f"{BASE}/{payment.id}", headers=await admin_headers())
    assert r.status_code == 200, r.text
    assert FULL_PHONE not in r.text
    assert "90 123-45-67" not in r.text
    assert "8600123412341234" not in r.text
    assert "tariff" not in r.text
    extra = r.json()["kassa"][0]["extra"]
    if phone is None:
        assert "phone" not in extra
    else:
        assert extra["phone"] == phone
    source_value = source.get("paymentSource")
    if isinstance(source_value, str):
        assert extra["source"] == source_value
    else:
        assert "source" not in extra
    assert set(extra) <= {"account", "service_id", "source", "phone"}


async def test_a_payment_with_several_kassa_rows_lists_them_oldest_first(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await make_user(db_session)
    topup = await _topup(db_session, user, "T7KQ4M2X")
    payment = await _payment(db_session, topup, provider="click", status="pending")
    for n, created in enumerate((T0 + timedelta(minutes=9), T0 + timedelta(minutes=1))):
        db_session.add(
            ClickTransaction(
                id=new_id(),
                click_trans_id=100 + n,
                service_id=1,
                payment_id=payment.id,
                account="T7KQ4M2X",
                amount=Decimal(50000),
                status="CANCELLED" if n == 0 else "PREPARED",
                prepare_time=created,
                cancel_time=created if n == 0 else None,
                created_at=created,
                updated_at=created,
            )
        )
    await db_session.commit()
    r = await integration_client.get(f"{BASE}/{payment.id}", headers=await admin_headers())
    assert [k["external_id"] for k in r.json()["kassa"]] == ["101", "100"]


async def test_detail_of_an_order_payment_shows_the_order(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user = await _named_user(db_session, "Bob")
    order = await make_order(db_session, user=user, status="paid", price_uzs=Decimal(171_800))
    payment = Payment(
        id=new_id(),
        number=order.number,
        purpose="order",
        order_id=order.id,
        user_id=user.id,
        provider="payme",
        provider_ref=f"payme:{order.number}",
        amount_uzs=order.price_uzs,
        status="succeeded",
        succeeded_at=T0,
    )
    db_session.add(payment)
    await db_session.commit()

    r = await integration_client.get(f"{BASE}/{payment.id}", headers=await admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["topup"] is None
    assert body["order"] == {"number": order.number, "status": "paid", "price_uzs": "171800"}
    assert body["payment"]["purpose"] == "order"
