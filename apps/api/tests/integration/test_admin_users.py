"""Admin users API: list, card, ban/unban, audited balance adjustment (M3 Task 9)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.users.api import set_roles
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import admin_adjust
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.conftest import ADMIN_STEAM_ID, CUSTOMER_STEAM_ID
from tests.integration.payments_factory import make_topup, make_user

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/users"
#: A redrawn fake trade link — never a real partner/token.
FAKE_LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734280&token=QwErTy7z"
ADMIN_ID = "00000000-0000-4000-8000-000000000001"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"admin-users-{uuid.uuid4()}"}


async def _by_steam(db: AsyncSession, steam_id: str) -> User:
    user = await db.scalar(select(User).where(User.steam_id == steam_id))
    assert user is not None
    await db.refresh(user)
    return user


async def _audit(db: AsyncSession, action: str) -> list[AdminAuditLog]:
    rows = await db.scalars(select(AdminAuditLog).where(AdminAuditLog.action == action))
    return list(rows)


async def _named(db: AsyncSession, name: str | None, *, sid: str | None = None) -> User:
    user = await make_user(db, sid)
    user.display_name = name
    await db.commit()
    return user


# --- the gate ---------------------------------------------------------------------------


#: Every route: method, path (``{id}`` = the target), body.
_ROUTES: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "", None),
    ("GET", "/{id}", None),
    ("POST", "/{id}/ban", {"reason": "spam bot"}),
    ("POST", "/{id}/unban", {"reason": "appeal ok"}),
    ("POST", "/{id}/wallet/adjust", {"amount_uzs": 1000, "reason": "goodwill"}),
]


@pytest.mark.parametrize("route", _ROUTES, ids=[f"{m} {p}" for m, p, _ in _ROUTES])
async def test_a_customer_is_403_on_every_admin_users_route(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    route: tuple[str, str, dict[str, object] | None],
) -> None:
    method, path, body = route
    h = await customer_headers()
    target = await make_user(db_session)
    url = BASE + path.format(id=target.id)
    r = await integration_client.request(method, url, json=body, headers={**h, **_key()})
    assert r.status_code == 403, r.text
    assert (await integration_client.request(method, url)).status_code == 401


# --- list -------------------------------------------------------------------------------


async def test_list_searches_by_name_and_by_exact_steam_id(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    alice = await _named(db_session, "Alice Smith", sid="76561198000000201")
    await _named(db_session, "Bob", sid="76561198000000202")
    percent = await _named(db_session, "100%_real", sid="76561198000000203")
    await _named(db_session, "100x real", sid="76561198000000204")

    r = await integration_client.get(BASE, params={"q": "aLiCe"}, headers=h)
    assert r.status_code == 200, r.text
    assert [u["id"] for u in r.json()["items"]] == [alice.id]

    r = await integration_client.get(BASE, params={"q": "76561198000000202"}, headers=h)
    assert [u["display_name"] for u in r.json()["items"]] == ["Bob"]

    # ``%`` and ``_`` are literal, not wildcards.
    r = await integration_client.get(BASE, params={"q": "100%_"}, headers=h)
    assert [u["id"] for u in r.json()["items"]] == [percent.id]

    # A partial Steam ID is not a match (exact 17 digits only).
    r = await integration_client.get(BASE, params={"q": "7656119800000020"}, headers=h)
    assert r.json()["items"] == []

    everyone = (await integration_client.get(BASE, headers=h)).json()
    assert len(everyone["items"]) == 5  # four + the admin
    assert everyone["next_cursor"] is None
    row = next(u for u in everyone["items"] if u["id"] == alice.id)
    assert set(row) == {
        "id",
        "display_name",
        "avatar_url",
        "steam_id",
        "roles",
        "banned_at",
        "created_at",
        "balance_uzs",
    }


async def test_list_shows_each_balance(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    rich = await make_user(db_session)
    poor = await make_user(db_session)
    await admin_adjust(
        db_session,
        user_id=rich.id,
        amount=Decimal(75000),
        reason="goodwill",
        admin_id=ADMIN_ID,
        idempotency_key="list-balance-key-0001",
    )
    await admin_adjust(
        db_session,
        user_id=rich.id,
        amount=Decimal(-5000),
        reason="double credit",
        admin_id=ADMIN_ID,
        idempotency_key="list-balance-key-0002",
    )
    await db_session.commit()
    items = (await integration_client.get(BASE, headers=h)).json()["items"]
    balances = {u["id"]: u["balance_uzs"] for u in items}
    assert balances[rich.id] == "70000"
    assert balances[poor.id] == "0"


async def test_list_pages_newest_first_without_duplicates(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    for _ in range(24):
        await make_user(db_session)
    seen: list[dict[str, str]] = []
    cursor: str | None = None
    for _ in range(4):
        params: dict[str, str | int] = {"limit": 10}
        if cursor is not None:
            params["cursor"] = cursor
        page = (await integration_client.get(BASE, params=params, headers=h)).json()
        seen.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert len(seen) == 25
    assert len({u["id"] for u in seen}) == 25
    stamps = [u["created_at"] for u in seen]
    assert stamps == sorted(stamps, reverse=True)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"cursor": "%%%nope"}])
async def test_list_refuses_bad_paging(
    integration_client: AsyncClient, admin_headers: Headers, params: dict[str, str | int]
) -> None:
    r = await integration_client.get(BASE, params=params, headers=await admin_headers())
    assert r.status_code == 422, r.text


async def test_list_query_count_is_constant(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    h = await admin_headers()

    async def _count(users: int) -> int:
        for i in range(users):
            u = await make_user(db_session)
            await admin_adjust(
                db_session,
                user_id=u.id,
                amount=Decimal(1000 + i),
                reason="seed",
                admin_id=ADMIN_ID,
                idempotency_key=f"count-{users}-{i}-padding",
            )
            await db_session.commit()
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

    assert await _count(5) == await _count(25)


# --- card -------------------------------------------------------------------------------


async def test_card_shows_the_profile_balance_entries_and_topups_with_a_masked_link(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    user = await _named(db_session, "Carol")
    user.trade_link = FAKE_LINK
    user.trade_link_verdict = "ok"
    await db_session.commit()
    topup = await make_topup(db_session, user=user, amount=Decimal(30000), status="pending")
    await admin_adjust(
        db_session,
        user_id=user.id,
        amount=Decimal(12000),
        reason="goodwill",
        admin_id=ADMIN_ID,
        idempotency_key="card-credit-key-0001",
    )
    await db_session.commit()

    r = await integration_client.get(f"{BASE}/{user.id}", headers=h)
    assert r.status_code == 200, r.text
    card = r.json()
    assert "QwErTy" not in r.text
    assert card["user"]["trade_link_masked"] == (
        "https://steamcommunity.com/tradeoffer/new/?partner=39734280&token=••••7z"
    )
    assert "trade_link" not in card["user"]
    assert card["user"]["display_name"] == "Carol"
    assert card["user"]["trade_link_verdict"] == "ok"
    assert card["balance_uzs"] == "12000"
    (entry,) = card["entries"]
    assert entry["kind"] == "admin_adjust"
    assert entry["amount_uzs"] == "+12000"
    assert entry["actor"] == f"admin:{ADMIN_ID}"
    assert entry["reason"] == "goodwill"
    (t,) = card["topups"]
    assert t == {
        "number": topup.number,
        "amount_uzs": "30000",
        "status": "pending",
        "provider": None,
        "created_at": t["created_at"],
        "succeeded_at": None,
    }


@pytest.mark.parametrize("bad_id", ["00000000-0000-4000-8000-0000000000ff", "not-a-uuid"])
async def test_card_of_an_unknown_user_is_404(
    integration_client: AsyncClient, admin_headers: Headers, bad_id: str
) -> None:
    h = await admin_headers()
    assert (await integration_client.get(f"{BASE}/{bad_id}", headers=h)).status_code == 404
    r = await integration_client.post(
        f"{BASE}/{bad_id}/ban", json={"reason": "spam bot"}, headers={**h, **_key()}
    )
    assert r.status_code == 404


# --- ban / unban ------------------------------------------------------------------------


async def test_ban_suspends_the_account_revokes_its_sessions_and_is_audited(
    integration_client: AsyncClient,
    admin_headers: Headers,
    customer_headers: Headers,
    db_session: AsyncSession,
) -> None:
    h = await admin_headers()
    # Signed in last, so the client's cookie jar holds the customer's refresh cookie.
    ch = await customer_headers()
    customer = await _by_steam(db_session, CUSTOMER_STEAM_ID)

    r = await integration_client.post(
        f"{BASE}/{customer.id}/ban", json={"reason": "chargeback fraud"}, headers={**h, **_key()}
    )
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["user"]["banned_at"] is not None
    assert card["user"]["ban_reason"] == "chargeback fraud"

    me = await integration_client.get("/api/v1/me", headers=ch)
    assert me.status_code == 403
    assert me.json()["type"].endswith("/account-suspended")
    refresh = await integration_client.post("/api/v1/auth/refresh")
    # Its refresh row was revoked by the ban: the refresh dies (and signs the app out).
    assert refresh.status_code == 401, refresh.text

    (row,) = await _audit(db_session, "users.ban")
    admin = await _by_steam(db_session, ADMIN_STEAM_ID)
    assert (row.actor_user_id, row.target_type, row.target_id) == (admin.id, "user", customer.id)
    assert row.payload == {"reason": "chargeback fraud"}


async def test_a_replayed_ban_writes_one_audit_row_and_another_body_is_409(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = {**(await admin_headers()), **_key()}
    target = await make_user(db_session)
    first = await integration_client.post(
        f"{BASE}/{target.id}/ban", json={"reason": "spam bot"}, headers=h
    )
    again = await integration_client.post(
        f"{BASE}/{target.id}/ban", json={"reason": "spam bot"}, headers=h
    )
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert len(await _audit(db_session, "users.ban")) == 1
    other = await integration_client.post(
        f"{BASE}/{target.id}/ban", json={"reason": "something else"}, headers=h
    )
    assert other.status_code == 409
    assert other.json()["code"] == "idempotency_mismatch"


async def test_banning_oneself_or_another_admin_is_409(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    me = await _by_steam(db_session, ADMIN_STEAM_ID)
    r = await integration_client.post(
        f"{BASE}/{me.id}/ban", json={"reason": "oops"}, headers={**h, **_key()}
    )
    assert (r.status_code, r.json()["code"]) == (409, "ban_self")

    other = await make_user(db_session)
    await set_roles(db_session, other, ["admin"])
    await db_session.commit()
    r = await integration_client.post(
        f"{BASE}/{other.id}/ban", json={"reason": "rogue admin"}, headers={**h, **_key()}
    )
    assert (r.status_code, r.json()["code"]) == (409, "ban_admin")
    assert await _audit(db_session, "users.ban") == []


async def test_ban_twice_and_unban_when_not_banned_are_409(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    r = await integration_client.post(
        f"{BASE}/{target.id}/unban", json={"reason": "nothing"}, headers={**h, **_key()}
    )
    assert (r.status_code, r.json()["code"]) == (409, "not_banned")
    await integration_client.post(
        f"{BASE}/{target.id}/ban", json={"reason": "spam bot"}, headers={**h, **_key()}
    )
    r = await integration_client.post(
        f"{BASE}/{target.id}/ban", json={"reason": "spam bot"}, headers={**h, **_key()}
    )
    assert (r.status_code, r.json()["code"]) == (409, "already_banned")


async def test_unban_clears_the_ban_and_is_audited(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    await integration_client.post(
        f"{BASE}/{target.id}/ban", json={"reason": "spam bot"}, headers={**h, **_key()}
    )
    unban_h = {**h, **_key()}
    r = await integration_client.post(
        f"{BASE}/{target.id}/unban", json={"reason": "appeal accepted"}, headers=unban_h
    )
    assert r.status_code == 200, r.text
    replay = await integration_client.post(
        f"{BASE}/{target.id}/unban", json={"reason": "appeal accepted"}, headers=unban_h
    )
    assert (replay.status_code, replay.json()) == (200, r.json())
    assert (r.json()["user"]["banned_at"], r.json()["user"]["ban_reason"]) == (None, None)
    (row,) = await _audit(db_session, "users.unban")
    assert row.payload == {"reason": "appeal accepted"}
    login = await integration_client.post(
        "/api/v1/auth/dev-login", json={"steam_id": target.steam_id}
    )
    assert login.status_code == 200


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        ({"reason": "no"}, None),
        ({"reason": "x" * 501}, None),
        ({}, None),
        ({"reason": "spam bot", "extra": 1}, None),
        ({"reason": "spam bot"}, {}),
        ({"reason": "spam bot"}, {"Idempotency-Key": "short"}),
    ],
)
async def test_ban_refuses_a_bad_body_or_key(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    body: dict[str, object],
    headers: dict[str, str] | None,
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    r = await integration_client.post(
        f"{BASE}/{target.id}/ban",
        json=body,
        headers={**h, **(_key() if headers is None else headers)},
    )
    assert r.status_code == 422, r.text


# --- wallet adjust ----------------------------------------------------------------------


async def test_adjust_credit_and_clawback_show_in_the_card_but_not_to_the_customer(
    integration_client: AsyncClient,
    admin_headers: Headers,
    customer_headers: Headers,
    db_session: AsyncSession,
) -> None:
    h = await admin_headers()
    ch = await customer_headers()
    customer = await _by_steam(db_session, CUSTOMER_STEAM_ID)
    admin = await _by_steam(db_session, ADMIN_STEAM_ID)
    url = f"{BASE}/{customer.id}/wallet/adjust"

    r = await integration_client.post(
        url, json={"amount_uzs": 50000, "reason": "compensation"}, headers={**h, **_key()}
    )
    assert r.status_code == 200, r.text
    assert r.json()["balance_uzs"] == "50000"
    r = await integration_client.post(
        url, json={"amount_uzs": -20000, "reason": "double credit"}, headers={**h, **_key()}
    )
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["balance_uzs"] == "30000"
    assert [(e["amount_uzs"], e["actor"], e["reason"]) for e in card["entries"]] == [
        ("-20000", f"admin:{admin.id}", "double credit"),
        ("+50000", f"admin:{admin.id}", "compensation"),
    ]

    rows = await _audit(db_session, "wallet.adjust")
    assert sorted((r.payload["amount_uzs"], r.payload["reason"]) for r in rows) == [
        (-20000, "double credit"),
        (50000, "compensation"),
    ]
    assert {(r.target_type, r.target_id) for r in rows} == {("user", customer.id)}

    mine = await integration_client.get("/api/v1/wallet/entries", headers=ch)
    assert [e["amount_uzs"] for e in mine.json()["items"]] == ["-20000", "+50000"]
    assert "double credit" not in mine.text
    assert "compensation" not in mine.text
    assert admin.id not in mine.text


async def test_a_clawback_below_zero_is_409_and_writes_nothing(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    url = f"{BASE}/{target.id}/wallet/adjust"
    await integration_client.post(
        url, json={"amount_uzs": 5000, "reason": "goodwill"}, headers={**h, **_key()}
    )
    r = await integration_client.post(
        url, json={"amount_uzs": -6000, "reason": "too much"}, headers={**h, **_key()}
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "balance_too_low"
    assert len(await _audit(db_session, "wallet.adjust")) == 1
    card = (await integration_client.get(f"{BASE}/{target.id}", headers=h)).json()
    assert card["balance_uzs"] == "5000"


async def test_a_replayed_adjust_posts_once_and_another_amount_is_409(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = {**(await admin_headers()), **_key()}
    target = await make_user(db_session)
    url = f"{BASE}/{target.id}/wallet/adjust"
    body = {"amount_uzs": 7000, "reason": "goodwill"}
    first = await integration_client.post(url, json=body, headers=h)
    again = await integration_client.post(url, json=body, headers=h)
    assert first.status_code == again.status_code == 200
    assert again.json()["balance_uzs"] == "7000"
    assert len(await _audit(db_session, "wallet.adjust")) == 1
    other = await integration_client.post(
        url, json={"amount_uzs": 8000, "reason": "goodwill"}, headers=h
    )
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_mismatch")
    # The same key on another user is another request too.
    someone = await make_user(db_session)
    r = await integration_client.post(f"{BASE}/{someone.id}/wallet/adjust", json=body, headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "idempotency_mismatch")


@pytest.mark.parametrize(
    "body",
    [
        {"amount_uzs": 0, "reason": "goodwill"},
        {"amount_uzs": 100_000_001, "reason": "goodwill"},
        {"amount_uzs": -100_000_001, "reason": "goodwill"},
        {"amount_uzs": "1000", "reason": "goodwill"},
        {"amount_uzs": 1000.5, "reason": "goodwill"},
        {"amount_uzs": 1000, "reason": "abc"},
        {"amount_uzs": 1000},
    ],
)
async def test_adjust_refuses_a_bad_body(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    body: dict[str, object],
) -> None:
    h = await admin_headers()
    target = await make_user(db_session)
    r = await integration_client.post(
        f"{BASE}/{target.id}/wallet/adjust", json=body, headers={**h, **_key()}
    )
    assert r.status_code == 422, r.text
    count = await db_session.scalar(select(func.count()).select_from(AdminAuditLog))
    assert count == 0
