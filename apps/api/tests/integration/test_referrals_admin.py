"""``/admin/referrals*``: partners created, edited, listed and paged; audited and keyed."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from uuid import uuid4

import pytest
from csmarket.core.errors import ConflictError
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.referrals import partners
from csmarket.modules.referrals.models import ReferralPartner
from csmarket.modules.referrals.schemas import PartnerIn
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user
from tests.integration.referrals_factory import attribute, make_partner, make_reward
from tests.integration.reviews_factory import delivered_order

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/referrals"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"test-admin-referral-{uuid4()}"}


async def _audit(db: AsyncSession, action: str) -> list[AdminAuditLog]:
    db.expire_all()
    q = select(AdminAuditLog).where(AdminAuditLog.action == action)
    return list((await db.scalars(q)).all())


async def _create(
    c: AsyncClient, h: dict[str, str], user_id: str, **body: object
) -> tuple[int, dict[str, object]]:
    payload: dict[str, object] = {"user_id": user_id, "code": "zufarmax", "percent": "1.5"}
    payload.update(body)
    r = await c.post(f"{BASE}/partners", json=payload, headers={**h, **_key()})
    return r.status_code, r.json()


async def test_create_adds_the_role_and_audits(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    user = await make_user(db_session)
    user_id = user.id
    status, body = await _create(integration_client, h, user_id, note="канал в TG")
    assert status == 201, body
    assert body["code"] == "zufarmax"
    assert body["percent"] == "1.5"
    assert body["term_months"] == 6
    assert body["active"] is True
    db_session.expire_all()
    fresh = await db_session.get(User, user_id)
    assert fresh is not None
    assert "partner" in fresh.roles
    [row] = await _audit(db_session, "referrals.partner.create")
    assert row.payload == {"code": "zufarmax", "percent": "1.5", "term_months": 6}


@pytest.mark.parametrize("code", ["ab", "Has Space", "кириллица", "x" * 33, "a_b"])
async def test_bad_codes_are_422(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers, code: str
) -> None:
    h = await admin_headers()
    user = await make_user(db_session)
    status, body = await _create(integration_client, h, user.id, code=code)
    assert status == 422
    assert body["code"] == "code_invalid"


async def test_code_is_lowercased_and_unique(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    first, second = await make_user(db_session), await make_user(db_session)
    status, body = await _create(integration_client, h, first.id, code=" ZufarMax ")
    assert (status, body["code"]) == (201, "zufarmax")
    status, body = await _create(integration_client, h, second.id, code="zufarmax")
    assert (status, body["code"]) == (409, "code_taken")
    status, body = await _create(integration_client, h, first.id, code="other")
    assert (status, body["code"]) == (409, "partner_exists")


async def test_unknown_user_is_404(integration_client: AsyncClient, admin_headers: Headers) -> None:
    h = await admin_headers()
    status, body = await _create(integration_client, h, str(uuid4()))
    assert (status, body["code"]) == (404, "user_not_found")


@pytest.mark.parametrize("percent", ["0", "0.05", "20.1", "1.25"])
async def test_percent_bounds_422(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers, percent: str
) -> None:
    h = await admin_headers()
    user = await make_user(db_session)
    status, _ = await _create(integration_client, h, user.id, percent=percent)
    assert status == 422


async def test_patch_term_to_forever_and_back(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    partner = await make_partner(db_session)
    url = f"{BASE}/partners/{partner.user_id}"
    r = await integration_client.patch(url, json={"term_months": None}, headers={**h, **_key()})
    assert r.status_code == 200, r.text
    assert r.json()["term_months"] is None
    r = await integration_client.patch(
        url, json={"term_months": 12, "active": False}, headers={**h, **_key()}
    )
    assert (r.json()["term_months"], r.json()["active"]) == (12, False)
    r = await integration_client.patch(url, json={"percent": "3"}, headers={**h, **_key()})
    assert r.json()["term_months"] == 12  # untouched when absent
    [*rows] = await _audit(db_session, "referrals.partner.update")
    assert len(rows) == 3
    assert rows[0].payload == {"term_months": None}


async def test_code_locked_after_an_attribution(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    partner = await make_partner(db_session)
    url = f"{BASE}/partners/{partner.user_id}"
    r = await integration_client.patch(url, json={"code": "renamed"}, headers={**h, **_key()})
    assert (r.status_code, r.json()["code"]) == (200, "renamed")
    await attribute(db_session, user=await make_user(db_session), partner=partner)
    r = await integration_client.patch(url, json={"code": "again"}, headers={**h, **_key()})
    assert (r.status_code, r.json()["code"]) == (409, "code_locked")


async def test_unknown_partner_patch_is_404(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    r = await integration_client.patch(
        f"{BASE}/partners/{uuid4()}", json={"active": False}, headers={**h, **_key()}
    )
    assert (r.status_code, r.json()["code"]) == (404, "partner_not_found")


async def test_list_totals_and_sort_by_revenue(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    small, big = await make_partner(db_session), await make_partner(db_session)
    buyer = await make_user(db_session)
    await attribute(db_session, user=buyer, partner=big)
    for status in ("held", "credited", "cancelled"):
        order = await delivered_order(db_session, user=buyer, price_uzs=Decimal(200_000))
        await make_reward(db_session, partner=big, order=order, status=status)
    order = await delivered_order(db_session, price_uzs=Decimal(50_000))
    await make_reward(db_session, partner=small, order=order, status="credited")
    r = await integration_client.get(f"{BASE}/partners", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["user_id"] for i in items] == [big.user_id, small.user_id]
    totals = items[0]["totals"]
    assert totals == {
        "visits": 0,
        "accounts": 1,
        "purchases": 2,
        "revenue_uzs": "400000",
        "held_uzs": "2000",
        "credited_uzs": "2000",
    }


async def test_detail_pages_rewards_with_cursor(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    partner = await make_partner(db_session)
    buyer = await make_user(db_session)
    numbers = []
    for days in range(52):
        order = await delivered_order(db_session, user=buyer, days_ago=days + 1)
        await make_reward(db_session, partner=partner, order=order)
        numbers.append(order.number)
    url = f"{BASE}/partners/{partner.user_id}"
    first = (await integration_client.get(url, headers=h)).json()
    assert [r["order_number"] for r in first["rewards"]] == numbers[:50]
    assert first["months"]
    second = (
        await integration_client.get(url, params={"cursor": first["next_cursor"]}, headers=h)
    ).json()
    assert [r["order_number"] for r in second["rewards"]] == numbers[50:]
    assert second["next_cursor"] is None
    bad = await integration_client.get(url, params={"cursor": "nope"}, headers=h)
    assert bad.status_code == 422


async def test_user_block_shows_who_brought_them(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    partner = await make_partner(db_session)
    buyer, walk_in = await make_user(db_session), await make_user(db_session)
    await attribute(db_session, user=buyer, partner=partner)
    body = (await integration_client.get(f"{BASE}/users/{buyer.id}", headers=h)).json()
    assert body["partner"]["code"] == partner.code
    assert body["attributed_at"] is not None
    assert body["is_partner"] is False
    body = (await integration_client.get(f"{BASE}/users/{walk_in.id}", headers=h)).json()
    assert body == {"partner": None, "attributed_at": None, "is_partner": False}
    body = (await integration_client.get(f"{BASE}/users/{partner.user_id}", headers=h)).json()
    assert body["is_partner"] is True


async def test_replay_returns_the_first_answer(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    user = await make_user(db_session)
    key = _key()
    payload = {"user_id": user.id, "code": "replayed", "percent": "1"}
    one = await integration_client.post(f"{BASE}/partners", json=payload, headers={**h, **key})
    two = await integration_client.post(f"{BASE}/partners", json=payload, headers={**h, **key})
    assert one.status_code == 201
    assert two.json() == one.json()
    count = await db_session.scalar(
        select(ReferralPartner.user_id).where(ReferralPartner.code == "replayed")
    )
    assert count == user.id


async def test_customers_get_403(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    assert (await integration_client.get(f"{BASE}/partners", headers=h)).status_code == 403


async def test_a_lost_race_is_409_not_500(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two admin tabs create at once: both pass the checks, the database decides."""
    admin = await make_user(db_session)
    taken = await make_partner(db_session, code="raced")
    newcomer = await make_user(db_session)
    admin_id, newcomer_id, taken_id = admin.id, newcomer.id, taken.user_id

    async def _free(*_: object, **__: object) -> None:
        return None

    async def _none(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(partners, "_code_free", _free)
    with pytest.raises(ConflictError) as code:
        await partners.create_partner(
            db_session,
            body=PartnerIn(user_id=newcomer_id, code="raced", percent=Decimal("1")),
            admin_id=admin_id,
        )
    assert code.value.extra["code"] == "code_taken"
    monkeypatch.setattr(partners, "_existing", _none)
    db_session.expunge_all()  # the other tab's session never saw the row
    with pytest.raises(ConflictError) as dup:
        await partners.create_partner(
            db_session,
            body=PartnerIn(user_id=taken_id, code="fresh-one", percent=Decimal("1")),
            admin_id=admin_id,
        )
    assert dup.value.extra["code"] == "partner_exists"
