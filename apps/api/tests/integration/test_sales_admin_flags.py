"""The admin's flags on «Выкуп» (review 2026-10-11): sale attentions listed and resolved
(SB-2), a payout reverted mid-transfer (SB-3 / M7), the sell block (SB-6), the settings
warning (SB-5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.sales.models import PayoutRequest, Sale, SaleBlock
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS, settings_warnings
from csmarket.modules.sales.status import apply_deposit, lock_sale
from csmarket.modules.skins.api import Bracket
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_deposit_client import deposit
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import make_request, make_sale

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/sales"


def _key(n: int) -> dict[str, str]:
    return {"Idempotency-Key": f"test-admin-flags-{n:06d}"}


async def _actions(db: AsyncSession) -> list[str]:
    rows = await db.scalars(select(AdminAuditLog.action).order_by(AdminAuditLog.created_at))
    return list(rows)


async def _fresh(db: AsyncSession, model: type[Sale] | type[PayoutRequest], pk: str) -> object:
    return await db.get(model, pk, populate_existing=True)


async def test_the_list_keeps_open_and_resolved_attentions(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    rolled = await make_sale(db_session, status="credited", attention_reason="rolled_back")
    late = await make_sale(db_session, status="closed", attention_reason="late_deposit")
    seen = await make_sale(
        db_session, status="credited", attention_reason="rolled_back", resolved_at=now()
    )
    await make_sale(db_session, status="credited")
    r = await integration_client.get(BASE, params={"attention": "open"}, headers=headers)
    body = r.json()
    assert {s["number"] for s in body["items"]} == {rolled.number, late.number}
    assert body["attention_open"] == 2
    assert all(s["attention_open"] for s in body["items"])
    r = await integration_client.get(BASE, params={"attention": "resolved"}, headers=headers)
    assert [s["number"] for s in r.json()["items"]] == [seen.number]
    r = await integration_client.get(BASE, params={"attention": "any"}, headers=headers)
    assert len(r.json()["items"]) == 3
    r = await integration_client.get(BASE, params={"reason": "late_deposit"}, headers=headers)
    assert [s["number"] for s in r.json()["items"]] == [late.number]
    r = await integration_client.get(BASE, headers=headers)
    assert (len(r.json()["items"]), r.json()["attention_open"]) == (4, 2)


async def test_resolve_stamps_once_is_audited_and_replayed(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    sale = await make_sale(db_session, status="credited", attention_reason="rolled_back")
    url = f"{BASE}/{sale.number}/resolve"
    first = await integration_client.post(
        url, json={"note": "lost 12 $"}, headers={**headers, **_key(1)}
    )
    again = await integration_client.post(
        url, json={"note": "lost 12 $"}, headers={**headers, **_key(1)}
    )
    assert first.status_code == again.status_code == 200, first.text
    body = first.json()
    assert (body["attention_reason"], body["attention_open"], body["resolved_note"]) == (
        "rolled_back",
        False,
        "lost 12 $",
    )
    assert body["resolved_by"] is not None
    other = await integration_client.post(url, json={}, headers={**headers, **_key(2)})
    assert other.status_code == 200  # already resolved: unchanged, no second audit row
    assert other.json()["resolved_note"] == "lost 12 $"
    assert await _actions(db_session) == ["sales.attention.resolve"]


async def test_resolve_without_an_attention_is_409_and_unknown_is_404(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    sale = await make_sale(db_session, status="credited")
    r = await integration_client.post(
        f"{BASE}/{sale.number}/resolve", json={}, headers={**headers, **_key(1)}
    )
    assert (r.status_code, r.json()["code"]) == (409, "nothing_to_resolve")
    r = await integration_client.post(
        f"{BASE}/S0000000/resolve", json={}, headers={**headers, **_key(2)}
    )
    assert r.status_code == 404


async def _rolled_back_payout(db: AsyncSession) -> tuple[Sale, PayoutRequest]:
    """A card sale paid out ``to_pay``, then reverted by Skinslink (SB-3)."""
    sale = await make_sale(db, status="payout", payout_to="card", payout_uzs=Decimal(147_400))
    request = await make_request(db, sale, status="to_pay")
    locked = await lock_sale(db, sale.id)
    assert locked is not None
    assert await apply_deposit(db, locked, deposit("reverted"), at=now()) == "attention"
    await db.commit()
    return sale, request


async def test_a_payout_reverted_mid_transfer_can_still_be_marked_paid(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    sale, request = await _rolled_back_payout(db_session)
    page = (await integration_client.get(f"{BASE}/payouts/{request.id}", headers=headers)).json()
    assert (page["can_decide"], page["can_cancel"]) == (True, True)
    # The transfer already went out: «Выплачено» is still recorded, with a stated reason.
    r = await integration_client.post(
        f"{BASE}/payouts/{request.id}/paid",
        json={"override_reason": "the transfer had already gone out"},
        headers={**headers, **_key(1)},
    )
    assert r.status_code == 200, r.text
    row = await _fresh(db_session, Sale, sale.id)
    assert isinstance(row, Sale)
    assert (row.status, row.attention_reason, row.resolved_at) == ("payout", "rolled_back", None)


async def test_a_payout_reverted_before_the_transfer_is_canceled_by_the_admin(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    sale, request = await _rolled_back_payout(db_session)
    url = f"{BASE}/payouts/{request.id}/cancel"
    first = await integration_client.post(
        url, json={"reason": "reverted"}, headers={**headers, **_key(1)}
    )
    again = await integration_client.post(
        url, json={"reason": "reverted"}, headers={**headers, **_key(1)}
    )
    assert first.status_code == again.status_code == 200, first.text
    assert first.json()["request"]["status"] == "canceled"
    assert (first.json()["can_decide"], first.json()["can_cancel"]) == (False, False)
    row = await _fresh(db_session, Sale, sale.id)
    assert isinstance(row, Sale)
    assert (row.status, row.attention_reason) == ("reverted", "rolled_back")
    assert row.resolved_at is not None
    kinds = (
        await db_session.scalars(select(EmailOutbox.kind).where(EmailOutbox.sale_id == sale.id))
    ).all()
    assert list(kinds) == ["sale_canceled"]
    assert await _actions(db_session) == ["sales.payout.cancel"]


async def test_only_a_reverted_payout_can_be_canceled(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    sale = await make_sale(db_session, status="payout", payout_to="card")
    request = await make_request(db_session, sale, status="to_pay")
    r = await integration_client.post(
        f"{BASE}/payouts/{request.id}/cancel", json={"reason": "x"}, headers={**headers, **_key(1)}
    )
    assert (r.status_code, r.json()["code"]) == (409, "payout_not_cancelable")


async def test_block_and_unblock_a_seller_audited(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    user = await make_user(db_session)
    url = f"{BASE}/blocks/{user.id}"
    r = await integration_client.get(url, headers=headers)
    assert (r.status_code, r.json()["blocked"]) == (200, False)
    r = await integration_client.put(
        url, json={"blocked": True, "reason": "chargeback"}, headers={**headers, **_key(1)}
    )
    assert r.status_code == 200, r.text
    assert (r.json()["blocked"], r.json()["reason"]) == (True, "chargeback")
    assert r.json()["blocked_by"] is not None
    listed = (await integration_client.get(f"{BASE}/blocks", headers=headers)).json()["items"]
    assert [b["user"]["id"] for b in listed] == [user.id]
    same = await integration_client.put(
        url, json={"blocked": True, "reason": "again"}, headers={**headers, **_key(2)}
    )
    assert same.json()["reason"] == "chargeback"  # a block in place keeps its first reason
    r = await integration_client.put(url, json={"blocked": False}, headers={**headers, **_key(3)})
    assert r.json()["blocked"] is False
    assert await db_session.get(SaleBlock, user.id, populate_existing=True) is None
    assert await _actions(db_session) == ["sales.user.block", "sales.user.unblock"]


async def test_a_block_needs_a_reason_and_a_known_user(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    unknown = "00000000-0000-4000-8000-000000000000"
    r = await integration_client.put(
        f"{BASE}/blocks/{unknown}", json={"blocked": True}, headers={**headers, **_key(1)}
    )
    assert r.status_code == 422
    r = await integration_client.put(
        f"{BASE}/blocks/{unknown}",
        json={"blocked": True, "reason": "x"},
        headers={**headers, **_key(2)},
    )
    assert r.status_code == 404
    assert (
        await integration_client.get(f"{BASE}/blocks/{unknown}", headers=headers)
    ).status_code == 404


async def test_the_dashboard_counts_the_sales_waiting_for_a_look(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    await make_sale(db_session, status="credited", attention_reason="rolled_back")
    await make_sale(db_session, status="hold", attention_reason="credit_blocked", resolved_at=now())
    r = await integration_client.get("/api/v1/admin/dashboard", headers=headers)
    assert r.json()["payouts"]["sales_attention"] == 1


async def test_the_settings_warn_when_the_bonus_eats_the_top_margin(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    view = (await integration_client.get(f"{BASE}/settings", headers=headers)).json()
    assert view["warnings"] == ["balance_bonus_eats_margin"]  # the default: 2 % − 2 % − 1 %
    doc = {
        **DEFAULT_SALE_SETTINGS.model_dump(mode="json"),
        "margin": [{"from_usd": "0", "percent": "10"}, {"from_usd": "100", "percent": "5"}],
        "balance_bonus_pct": "2",
        "max_sale_usd": "500",
    }
    r = await integration_client.put(f"{BASE}/settings", json=doc, headers={**headers, **_key(1)})
    assert r.status_code == 200, r.text
    assert (r.json()["warnings"], r.json()["settings"]["max_sale_usd"]) == ([], "500")


async def test_the_warning_sits_exactly_at_break_even() -> None:
    def doc(top: str, bonus: str) -> object:
        return DEFAULT_SALE_SETTINGS.model_copy(
            update={
                "margin": [
                    Bracket(from_usd=Decimal(0), percent=Decimal(10)),
                    Bracket(from_usd=Decimal(100), percent=Decimal(top)),
                ],
                "balance_bonus_pct": Decimal(bonus),
            }
        )

    assert settings_warnings(doc("3", "2")) == ["balance_bonus_eats_margin"]  # type: ignore[arg-type]
    assert settings_warnings(doc("3.01", "2")) == []  # type: ignore[arg-type]
