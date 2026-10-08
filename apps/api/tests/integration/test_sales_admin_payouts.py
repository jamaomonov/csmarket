# apps/api/tests/integration/test_sales_admin_payouts.py
"""«Заявки на выплату»: the queue, a request's page, the audited reveal, paid and reject."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.sales.models import PayoutRequest, Sale
from csmarket.modules.sales.payouts import cancel_request
from csmarket.modules.wallet.api import user_balance
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.sales_factory import HUMO, make_request, make_sale

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/sales/payouts"


def _key(n: int) -> dict[str, str]:
    return {"Idempotency-Key": f"test-admin-payout-{n:06d}"}


async def _payable(db: AsyncSession) -> PayoutRequest:
    sale = await make_sale(db, status="payout", payout_to="card", payout_uzs=Decimal(147_400))
    return await make_request(db, sale, status="to_pay")


async def _audit(db: AsyncSession) -> list[tuple[str, dict[str, object]]]:
    rows = await db.execute(
        select(AdminAuditLog.action, AdminAuditLog.payload).order_by(AdminAuditLog.created_at)
    )
    return [(a, p) for a, p in rows.all()]


async def test_the_queue_has_tabs_with_counts_and_masks_the_card(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    waiting = await make_sale(db_session, status="hold", payout_to="card")
    await make_request(db_session, waiting, status="waiting_hold")
    r = await integration_client.get(BASE, params={"status": "to_pay"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["counts"] == {
        "waiting_hold": 1,
        "to_pay": 1,
        "paid": 0,
        "rejected": 0,
        "canceled": 0,
    }
    [row] = body["items"]
    assert (row["id"], row["card_masked"], row["card_type"], row["amount_uzs"]) == (
        request.id,
        "•••• 9015",
        "humo",
        "147400",
    )
    assert HUMO not in r.text


async def test_the_card_number_leaves_only_through_the_audited_reveal(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    page = await integration_client.get(f"{BASE}/{request.id}", headers=headers)
    assert page.status_code == 200
    assert HUMO not in page.text
    with capture_logs() as logs:
        shown = await integration_client.post(
            f"{BASE}/{request.id}/reveal", json={"purpose": "show"}, headers=headers
        )
        copied = await integration_client.post(
            f"{BASE}/{request.id}/reveal", json={"purpose": "copy"}, headers=headers
        )
        paid = await integration_client.post(
            f"{BASE}/{request.id}/paid", json={"note": "Click"}, headers={**headers, **_key(1)}
        )
    assert shown.json() == copied.json() == {"number": HUMO}
    assert paid.status_code == 200
    assert HUMO not in paid.text
    assert HUMO not in repr(logs)
    assert [a for a, _ in await _audit(db_session)] == [
        "sales.card.show",
        "sales.card.copy",
        "sales.payout.paid",
    ]
    assert HUMO not in repr(await _audit(db_session))
    replays = (
        await db_session.execute(text("SELECT response_body::text FROM idempotent_responses"))
    ).scalars()
    assert all(HUMO not in body for body in replays)


async def test_paid_stamps_the_request_writes_a_letter_and_replays(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    url = f"{BASE}/{request.id}/paid"
    first = await integration_client.post(
        url, json={"note": "Click #1"}, headers={**headers, **_key(2)}
    )
    again = await integration_client.post(
        url, json={"note": "Click #1"}, headers={**headers, **_key(2)}
    )
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert (
        first.json()["request"]["status"],
        first.json()["note"],
        first.json()["can_decide"],
    ) == (
        "paid",
        "Click #1",
        False,
    )
    letter = await db_session.scalar(select(EmailOutbox).where(EmailOutbox.kind == "sale_paid"))
    assert letter is not None
    assert (letter.payload["to"], letter.payload["last4"]) == ("card", "9015")
    other_key = await integration_client.post(
        url, json={"note": "x"}, headers={**headers, **_key(3)}
    )
    assert (other_key.status_code, other_key.json()["code"]) == (409, "payout_not_payable")


async def test_reject_credits_the_amount_before_the_fee_to_the_balance(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)  # items 155 200, fee 7 800, card 147 400
    r = await integration_client.post(
        f"{BASE}/{request.id}/reject",
        json={"reason": "Карта заблокирована"},
        headers={**headers, **_key(4)},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["request"]["status"], r.json()["reject_reason"]) == (
        "rejected",
        "Карта заблокирована",
    )
    assert await user_balance(db_session, request.user_id) == Decimal(155_200)
    letter = await db_session.scalar(select(EmailOutbox).where(EmailOutbox.kind == "sale_paid"))
    assert letter is not None
    assert letter.payload["reason"] == "Карта заблокирована"
    assert (letter.payload["to"], letter.payload["rejected"], letter.payload["last4"]) == (
        "balance",
        "true",
        "9015",
    )
    again = await integration_client.post(
        f"{BASE}/{request.id}/reject", json={"reason": "again"}, headers={**headers, **_key(5)}
    )
    assert (again.status_code, again.json()["code"]) == (409, "payout_not_payable")
    assert await user_balance(db_session, request.user_id) == Decimal(155_200)


async def test_a_request_still_waiting_for_its_money_cannot_be_paid_or_rejected(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    sale = await make_sale(db_session, status="hold", payout_to="card")
    request = await make_request(db_session, sale, status="waiting_hold")
    for n, (action, body) in enumerate((("paid", {}), ("reject", {"reason": "x"}))):
        r = await integration_client.post(
            f"{BASE}/{request.id}/{action}", json=body, headers={**headers, **_key(10 + n)}
        )
        assert (r.status_code, r.json()["code"]) == (409, "payout_not_payable")
    assert await user_balance(db_session, sale.user_id) == 0


async def test_reject_needs_a_reason_and_writes_need_a_key(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    no_reason = await integration_client.post(
        f"{BASE}/{request.id}/reject", json={"reason": ""}, headers={**headers, **_key(6)}
    )
    no_key = await integration_client.post(f"{BASE}/{request.id}/paid", json={}, headers=headers)
    assert (no_reason.status_code, no_key.status_code) == (422, 422)


async def test_the_page_shows_the_breakdown_items_and_history(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    body = (await integration_client.get(f"{BASE}/{request.id}", headers=headers)).json()
    sale = body["sale"]
    assert (sale["items_uzs"], sale["fee_uzs"], sale["payout_uzs"]) == ("155200", "7800", "147400")
    assert [i["asset_id"] for i in sale["items"]] == ["100", "101"]
    assert [s["number"] for s in body["history_sales"]] == [sale["number"]]
    assert [p["id"] for p in body["history_payouts"]] == [request.id]
    assert body["can_decide"] is True


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/settings", None),
        ("PUT", "/settings", {}),
        ("GET", "", None),
        ("GET", "/S7K2M9QX", None),
        ("GET", "/payouts", None),
        ("GET", "/payouts/{id}", None),
        ("POST", "/payouts/{id}/paid", {}),
        ("POST", "/payouts/{id}/reject", {"reason": "x"}),
        ("POST", "/payouts/{id}/reveal", {"purpose": "show"}),
    ],
)
async def test_customers_are_403(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    *,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    request = await _payable(db_session)
    headers = {**await customer_headers(), **_key(30)}
    r = await integration_client.request(
        method, "/api/v1/admin/sales" + path.format(id=request.id), json=body, headers=headers
    )
    assert r.status_code == 403


async def test_a_request_a_revert_already_canceled_cannot_be_paid_or_rejected(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    request = await _payable(db_session)
    # The sale was reverted (the sale lock, then the request) between the page and the click.
    sale = await db_session.get(Sale, request.sale_id, populate_existing=True)
    assert sale is not None
    sale.status = "reverted"
    await cancel_request(db_session, sale)
    await db_session.commit()
    for n, (action, body) in enumerate((("paid", {}), ("reject", {"reason": "x"}))):
        r = await integration_client.post(
            f"{BASE}/{request.id}/{action}", json=body, headers={**headers, **_key(20 + n)}
        )
        assert (r.status_code, r.json()["code"]) == (409, "payout_not_payable")
    assert await user_balance(db_session, request.user_id) == 0
    assert [a for a, _ in await _audit(db_session)] == []


async def test_the_queue_pages_by_cursor(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    made = {(await _payable(db_session)).id for _ in range(3)}
    first = (await integration_client.get(BASE, params={"limit": 2}, headers=headers)).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    second = (
        await integration_client.get(
            BASE, params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    assert {r["id"] for r in first["items"] + second["items"]} == made
