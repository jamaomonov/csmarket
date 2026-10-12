# apps/api/tests/integration/test_sales_admin_payout_ops.py
"""«Заявки на выплату», admin review 2026-10-12: the claim, banned / frozen sellers, the risk
block, the oldest-first queue with search and totals, and the undo."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.sales.cards import backfill_fingerprints, card_fingerprint
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import debit_purchase, user_account, user_balance
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import dev_login_headers
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import HUMO, UZCARD, make_card, make_request, make_sale

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/sales/payouts"
#: A second admin (fake steamid64).
OTHER_ADMIN = "76561198000000007"


def _key(n: int) -> dict[str, str]:
    return {"Idempotency-Key": f"test-admin-payout-ops-{n:06d}"}


async def _payable(db: AsyncSession, **over: Any) -> PayoutRequest:  # Any: factory kwargs
    sale = await make_sale(db, status="payout", payout_to="card", payout_uzs=Decimal(147_400))
    return await make_request(db, sale, **{"status": "to_pay", **over})


async def _actions(db: AsyncSession) -> list[str]:
    rows = await db.scalars(select(AdminAuditLog.action).order_by(AdminAuditLog.created_at))
    return list(rows.all())


async def _fresh(db: AsyncSession, request: PayoutRequest) -> PayoutRequest:
    got = await db.get(PayoutRequest, request.id, populate_existing=True)
    assert got is not None
    return got


async def test_a_claim_keeps_other_admins_off_until_they_take_it_over(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    mine = await admin_headers()
    other = await dev_login_headers(integration_client, steam_id=OTHER_ADMIN, admin=True)
    request = await _payable(db_session)
    url = f"{BASE}/{request.id}"
    claimed = await integration_client.post(f"{url}/claim", json={}, headers={**mine, **_key(1)})
    again = await integration_client.post(f"{url}/claim", json={}, headers={**mine, **_key(1)})
    assert claimed.status_code == again.status_code == 200, claimed.text
    assert claimed.json() == again.json()
    row = claimed.json()["request"]
    assert row["claimed_by"]["id"] is not None
    assert row["claimed_until"] is not None
    for path, body, n in (
        ("reveal", {"purpose": "copy"}, 2),
        ("paid", {}, 3),
        ("reject", {"reason": "x"}, 4),
        ("release", None, 5),
    ):
        r = await integration_client.post(f"{url}/{path}", json=body, headers={**other, **_key(n)})
        assert (r.status_code, r.json()["code"]) == (409, "payout_claimed"), path
    taken = await integration_client.post(
        f"{url}/claim", json={"takeover": True}, headers={**other, **_key(6)}
    )
    assert taken.status_code == 200
    back = await integration_client.post(f"{url}/paid", json={}, headers={**mine, **_key(7)})
    assert (back.status_code, back.json()["code"]) == (409, "payout_claimed")
    paid = await integration_client.post(f"{url}/paid", json={}, headers={**other, **_key(8)})
    assert paid.status_code == 200
    assert paid.json()["request"]["claimed_by"] is None
    assert await _actions(db_session) == [
        "sales.payout.claim",
        "sales.payout.takeover",
        "sales.payout.paid",
    ]


async def test_a_claim_expires_and_can_be_released(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    mine = await admin_headers()
    other = await dev_login_headers(integration_client, steam_id=OTHER_ADMIN, admin=True)
    request = await _payable(db_session)
    url = f"{BASE}/{request.id}"
    await integration_client.post(f"{url}/claim", json={}, headers={**mine, **_key(10)})
    released = await integration_client.post(f"{url}/release", headers={**mine, **_key(11)})
    assert released.status_code == 200
    assert released.json()["request"]["claimed_by"] is None
    # The other admin's claim from 16 minutes ago no longer holds anyone back.
    other_id = (await integration_client.get("/api/v1/me", headers=other)).json()["id"]
    stale = await _fresh(db_session, request)
    stale.claimed_by, stale.claimed_at = other_id, now() - timedelta(minutes=16)
    await db_session.commit()
    page = (await integration_client.get(url, headers=mine)).json()
    assert page["request"]["claimed_by"] is None
    paid = await integration_client.post(f"{url}/paid", json={}, headers={**mine, **_key(12)})
    assert paid.status_code == 200
    assert "sales.payout.release" in await _actions(db_session)


async def test_reveal_only_while_payable(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session, status="paid", paid_at=now())
    r = await integration_client.post(
        f"{BASE}/{request.id}/reveal", json={"purpose": "show"}, headers=headers
    )
    assert (r.status_code, r.json()["code"]) == (409, "payout_not_payable")


async def test_a_banned_seller_is_paid_only_with_an_override(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    user = await db_session.get(User, request.user_id)
    assert user is not None
    user.banned_at, user.ban_reason = now(), "fraud"
    await db_session.commit()
    page = (await integration_client.get(f"{BASE}/{request.id}", headers=headers)).json()
    assert page["paid_needs_override"] is True
    assert page["risk"]["banned"] is True
    assert "banned" in page["request"]["flags"]
    url = f"{BASE}/{request.id}/paid"
    refused = await integration_client.post(url, json={}, headers={**headers, **_key(20)})
    assert (refused.status_code, refused.json()["code"]) == (409, "payout_user_blocked")
    ok = await integration_client.post(
        url, json={"override_reason": "owner said pay"}, headers={**headers, **_key(21)}
    )
    assert ok.status_code == 200, ok.text
    payload = await db_session.scalar(
        select(AdminAuditLog.payload).where(AdminAuditLog.action == "sales.payout.paid")
    )
    assert payload is not None
    assert payload["override"] == "owner said pay"


async def test_a_reverted_sale_is_paid_only_with_an_override(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    """Skinslink reverted the trade while the request was payable: the seller has the skins back."""
    headers = await admin_headers()
    request = await _payable(db_session)
    sale = await db_session.get(Sale, request.sale_id)
    assert sale is not None
    sale.attention_reason = "rolled_back"
    await db_session.commit()
    page = (await integration_client.get(f"{BASE}/{request.id}", headers=headers)).json()
    assert page["paid_needs_override"] is True
    assert "rolled_back" in page["request"]["flags"]
    queue = (await integration_client.get(BASE, headers=headers)).json()
    assert any("rolled_back" in row["flags"] for row in queue["items"])
    url = f"{BASE}/{request.id}/paid"
    refused = await integration_client.post(url, json={}, headers={**headers, **_key(40)})
    assert (refused.status_code, refused.json()["code"]) == (409, "payout_sale_reverted")
    assert (await _fresh(db_session, request)).status == "to_pay"
    ok = await integration_client.post(
        url, json={"override_reason": "seller re-sent the skins"}, headers={**headers, **_key(41)}
    )
    assert ok.status_code == 200, ok.text


async def test_a_frozen_wallet_blocks_paid_and_reject_says_why(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    wallet = await user_account(db_session, request.user_id)
    wallet.status = "frozen"
    await db_session.commit()
    rejected = await integration_client.post(
        f"{BASE}/{request.id}/reject", json={"reason": "x"}, headers={**headers, **_key(30)}
    )
    assert (rejected.status_code, rejected.json()["code"]) == (409, "wallet_frozen")
    paid = await integration_client.post(
        f"{BASE}/{request.id}/paid", json={}, headers={**headers, **_key(31)}
    )
    assert (paid.status_code, paid.json()["code"]) == (409, "payout_user_blocked")
    assert (await _fresh(db_session, request)).status == "to_pay"


async def test_the_risk_block_finds_the_same_card_on_another_account(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    other = await make_user(db_session)
    await make_card(db_session, other)  # the same HUMO number
    earlier = await make_sale(
        db_session, user=other, status="payout", payout_to="card", payout_uzs=Decimal(1000)
    )
    await make_request(db_session, earlier, status="paid", paid_at=now())
    page = (await integration_client.get(f"{BASE}/{request.id}", headers=headers)).json()
    risk = page["risk"]
    assert [u["id"] for u in risk["shared_card_users"]] == [other.id]
    assert risk["card_known"] is True
    assert risk["card_paid_uzs"] == "1000"
    assert (risk["sold_count"], risk["sold_uzs"], risk["paid_count"]) == (1, "147400", 0)
    assert risk["day_count"] == 1
    assert risk["steam_url"].startswith("https://steamcommunity.com/profiles/")
    assert set(page["request"]["flags"]) == {"new_account", "shared_card"}
    assert HUMO not in str(page)


async def test_the_queue_is_oldest_first_searchable_and_totalled(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    late = await _payable(db_session, to_pay_at=now() - timedelta(hours=1))
    early = await _payable(db_session, to_pay_at=now() - timedelta(hours=50))
    user = await make_user(db_session)
    card = await make_card(db_session, user, card_type="uzcard", number=UZCARD)
    sale = await make_sale(db_session, user=user, status="payout", payout_to="card", card=card)
    paid = await make_request(db_session, sale, status="paid", paid_at=now())
    body = (await integration_client.get(BASE, headers=headers)).json()
    assert [r["id"] for r in body["items"]] == [early.id, late.id]
    assert body["totals"]["to_pay_count"] == 2
    assert body["totals"]["to_pay_uzs"] == "294800"
    assert (body["totals"]["paid_today_count"], body["totals"]["paid_today_uzs"]) == (
        1,
        "155200",
    )
    page = (await integration_client.get(BASE, params={"limit": 1}, headers=headers)).json()
    rest = (
        await integration_client.get(
            BASE, params={"limit": 1, "cursor": page["next_cursor"]}, headers=headers
        )
    ).json()
    assert [r["id"] for r in page["items"] + rest["items"]] == [early.id, late.id]
    by_last4 = (
        await integration_client.get(BASE, params={"status": "all", "q": "9012"}, headers=headers)
    ).json()
    assert [r["id"] for r in by_last4["items"]] == [paid.id]
    by_number = (
        await integration_client.get(
            BASE, params={"status": "all", "q": sale.number.lower()}, headers=headers
        )
    ).json()
    assert [r["id"] for r in by_number["items"]] == [paid.id]


async def test_undo_paid_puts_it_back_and_drops_the_waiting_letter(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    url = f"{BASE}/{request.id}"
    paid = await integration_client.post(f"{url}/paid", json={}, headers={**headers, **_key(40)})
    assert paid.json()["undo_until"] is not None
    undone = await integration_client.post(
        f"{url}/undo", json={"reason": "wrong row"}, headers={**headers, **_key(41)}
    )
    assert undone.status_code == 200, undone.text
    assert (undone.json()["request"]["status"], undone.json()["can_decide"]) == ("to_pay", True)
    letters = await db_session.scalar(select(func.count()).select_from(EmailOutbox))
    assert letters == 0
    again = await integration_client.post(f"{url}/paid", json={}, headers={**headers, **_key(42)})
    assert again.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(EmailOutbox)) == 1
    assert "sales.payout.undo" in await _actions(db_session)


async def test_only_the_admin_who_marked_it_paid_can_undo_it(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    """Another admin cannot know whether the transfer went out: an undo by them could pay twice."""
    headers = await admin_headers()
    request = await _payable(db_session)
    url = f"{BASE}/{request.id}"
    paid = await integration_client.post(f"{url}/paid", json={}, headers={**headers, **_key(50)})
    assert paid.status_code == 200, paid.text
    other = await dev_login_headers(integration_client, steam_id=OTHER_ADMIN, admin=True)
    refused = await integration_client.post(
        f"{url}/undo", json={"reason": "not mine"}, headers={**other, **_key(51)}
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "undo_not_yours")
    assert (await _fresh(db_session, request)).status == "paid"


async def test_undo_reject_takes_the_credit_back_and_a_new_reject_credits_again(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)  # items 155 200
    url = f"{BASE}/{request.id}"
    await integration_client.post(
        f"{url}/reject", json={"reason": "x"}, headers={**headers, **_key(50)}
    )
    assert await user_balance(db_session, request.user_id) == Decimal(155_200)
    undone = await integration_client.post(
        f"{url}/undo", json={"reason": "wrong row"}, headers={**headers, **_key(51)}
    )
    assert undone.status_code == 200, undone.text
    assert await user_balance(db_session, request.user_id) == 0
    await integration_client.post(
        f"{url}/reject", json={"reason": "y"}, headers={**headers, **_key(52)}
    )
    assert await user_balance(db_session, request.user_id) == Decimal(155_200)


async def test_undo_reject_is_refused_once_the_money_is_spent_or_late(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    url = f"{BASE}/{request.id}"
    await integration_client.post(
        f"{url}/reject", json={"reason": "x"}, headers={**headers, **_key(60)}
    )
    await debit_purchase(
        db_session, user_id=request.user_id, order_id=new_id(), amount=Decimal(100_000)
    )
    await db_session.commit()
    spent = await integration_client.post(
        f"{url}/undo", json={"reason": "wrong"}, headers={**headers, **_key(61)}
    )
    assert (spent.status_code, spent.json()["code"]) == (409, "balance_spent")
    assert await user_balance(db_session, request.user_id) == Decimal(55_200)
    late = await _fresh(db_session, request)
    late.rejected_at = now() - timedelta(minutes=11)
    await db_session.commit()
    expired = await integration_client.post(
        f"{url}/undo", json={"reason": "wrong"}, headers={**headers, **_key(62)}
    )
    assert (expired.status_code, expired.json()["code"]) == (409, "undo_expired")


async def test_settings_save_refuses_a_stale_tab(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    view = (await integration_client.get("/api/v1/admin/sales/settings", headers=headers)).json()
    doc = view["settings"]
    first = await integration_client.put(
        "/api/v1/admin/sales/settings",
        json=doc,
        headers={**headers, **_key(70), "If-Match": "none"},
    )
    assert first.status_code == 200, first.text
    stale = await integration_client.put(
        "/api/v1/admin/sales/settings",
        json={**doc, "enabled": True},
        headers={**headers, **_key(71), "If-Match": "none"},
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "settings_stale")
    fresh = await integration_client.put(
        "/api/v1/admin/sales/settings",
        json={**doc, "enabled": True},
        headers={**headers, **_key(72), "If-Match": first.json()["updated_at"]},
    )
    assert fresh.status_code == 200, fresh.text
    bad = await integration_client.put(
        "/api/v1/admin/sales/settings",
        json=doc,
        headers={**headers, **_key(73), "If-Match": "yesterday"},
    )
    assert bad.status_code == 422


async def test_the_backfill_fills_cards_saved_before_the_fingerprint(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    card = await make_card(db_session, user, fingerprint=False)
    assert await backfill_fingerprints(db_session) == 1
    await db_session.commit()
    got = await db_session.get(PayoutCard, card.id, populate_existing=True)
    assert got is not None
    assert got.number_fp == card_fingerprint(HUMO)
    assert await backfill_fingerprints(db_session) == 0


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/{id}/claim", {}),
        ("/{id}/release", None),
        ("/{id}/undo", {"reason": "x"}),
    ],
)
async def test_customers_are_403(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    *,
    path: str,
    body: dict[str, object] | None,
) -> None:
    request = await _payable(db_session)
    headers = {**await customer_headers(), **_key(90)}
    r = await integration_client.post(BASE + path.format(id=request.id), json=body, headers=headers)
    assert r.status_code == 403


async def test_replays_and_edges_of_claim_release_and_undo(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    url = f"{BASE}/{request.id}"
    # Releasing a request nobody holds is a quiet no-op, and a replay answers the same.
    first = await integration_client.post(f"{url}/release", headers={**headers, **_key(100)})
    again = await integration_client.post(f"{url}/release", headers={**headers, **_key(100)})
    assert first.status_code == again.status_code == 200
    assert "sales.payout.release" not in await _actions(db_session)
    # Undo of a request nobody decided is refused.
    early = await integration_client.post(
        f"{url}/undo", json={"reason": "x"}, headers={**headers, **_key(101)}
    )
    assert (early.status_code, early.json()["code"]) == (409, "undo_expired")
    await integration_client.post(
        f"{url}/reject", json={"reason": "x"}, headers={**headers, **_key(102)}
    )
    replay = await integration_client.post(
        f"{url}/reject", json={"reason": "x"}, headers={**headers, **_key(102)}
    )
    assert replay.status_code == 200
    claim_paid = await integration_client.post(
        f"{url}/claim", json={}, headers={**headers, **_key(103)}
    )
    assert (claim_paid.status_code, claim_paid.json()["code"]) == (409, "payout_not_payable")
    wallet = await user_account(db_session, request.user_id)
    wallet.status = "frozen"
    await db_session.commit()
    frozen = await integration_client.post(
        f"{url}/undo", json={"reason": "x"}, headers={**headers, **_key(104)}
    )
    assert (frozen.status_code, frozen.json()["code"]) == (409, "wallet_frozen")
    wallet = await user_account(db_session, request.user_id)
    wallet.status = "active"
    await db_session.commit()
    undone = await integration_client.post(
        f"{url}/undo", json={"reason": "x"}, headers={**headers, **_key(105)}
    )
    undone_again = await integration_client.post(
        f"{url}/undo", json={"reason": "x"}, headers={**headers, **_key(105)}
    )
    assert undone.status_code == undone_again.status_code == 200
    assert undone.json() == undone_again.json()


async def test_newest_first_tabs_page_by_cursor(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    made = [await _payable(db_session, status="paid", paid_at=now()) for _ in range(3)]
    first = (
        await integration_client.get(BASE, params={"status": "paid", "limit": 2}, headers=headers)
    ).json()
    rest = (
        await integration_client.get(
            BASE,
            params={"status": "paid", "limit": 2, "cursor": first["next_cursor"]},
            headers=headers,
        )
    ).json()
    assert [r["id"] for r in first["items"] + rest["items"]] == [m.id for m in reversed(made)]
    nobody = (
        await integration_client.get(
            BASE, params={"status": "all", "q": "no-such-seller"}, headers=headers
        )
    ).json()
    assert nobody["items"] == []
