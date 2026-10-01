"""``GET /admin/audit``: the audit trail, filtered and paged (M3 Task 10)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.payments_factory import make_user

Headers = Callable[[], Awaitable[dict[str, str]]]
URL = "/api/v1/admin/audit"
T0 = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


async def _admin(db: AsyncSession, name: str | None) -> User:
    user = await make_user(db)
    user.display_name = name
    await db.commit()
    return user


async def _row(
    db: AsyncSession,
    actor: User,
    *,
    action: str = "users.ban",
    target_type: str = "user",
    target_id: str = "t-1",
    payload: dict[str, str | int | bool | None] | None = None,
    minutes: int = 0,
) -> AdminAuditLog:
    row = AdminAuditLog(
        id=str(uuid.uuid4()),
        actor_user_id=actor.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload=dict(payload or {}),
        created_at=T0 + timedelta(minutes=minutes),
    )
    db.add(row)
    await db.commit()
    return row


async def test_a_customer_is_403_and_anonymous_401(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    assert (await integration_client.get(URL, headers=await customer_headers())).status_code == 403
    assert (await integration_client.get(URL)).status_code == 401


async def test_rows_carry_actor_and_payload_newest_first(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    ann = await _admin(db_session, "Ann")
    anon = await _admin(db_session, None)
    old = await _row(db_session, ann, payload={"reason": "spam"}, minutes=0)
    new = await _row(
        db_session,
        anon,
        action="wallet.adjust",
        target_id="u-9",
        payload={"amount_uzs": -5000, "reason": "double credit"},
        minutes=3,
    )
    r = await integration_client.get(URL, headers=await admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next_cursor"] is None
    assert body["items"] == [
        {
            "id": new.id,
            "created_at": "2026-09-30T10:03:00Z",
            "action": "wallet.adjust",
            "target_type": "user",
            "target_id": "u-9",
            "actor": {"id": anon.id, "display_name": None},
            "payload": {"amount_uzs": -5000, "reason": "double credit"},
        },
        {
            "id": old.id,
            "created_at": "2026-09-30T10:00:00Z",
            "action": "users.ban",
            "target_type": "user",
            "target_id": "t-1",
            "actor": {"id": ann.id, "display_name": "Ann"},
            "payload": {"reason": "spam"},
        },
    ]


async def test_filters_combine(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    ann = await _admin(db_session, "Ann")
    bob = await _admin(db_session, "Bob")
    a = await _row(db_session, ann, action="users.ban", target_id="u-1", minutes=0)
    b = await _row(db_session, bob, action="users.ban", target_id="u-2", minutes=1)
    c = await _row(
        db_session, ann, action="skins.item.hide", target_type="skin_item", target_id="7", minutes=2
    )
    d = await _row(db_session, bob, action="wallet.adjust", target_id="u-1", minutes=3)
    h = await admin_headers()

    async def ids(**params: str) -> list[str]:
        r = await integration_client.get(URL, params=params, headers=h)
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["items"]]

    assert await ids(action="users.ban") == [b.id, a.id]
    assert await ids(target_type="skin_item") == [c.id]
    assert await ids(target_id="u-1") == [d.id, a.id]
    assert await ids(actor_id=ann.id) == [c.id, a.id]
    assert await ids(actor_id=bob.id, target_id="u-1") == [d.id]
    assert await ids(action="users.ban", actor_id=ann.id, target_id="u-1") == [a.id]
    assert await ids(action="users.%") == []  # exact match, not a pattern
    assert await ids(action="nothing") == []
    assert len(await ids()) == 4


@pytest.mark.parametrize(
    "params",
    [
        {"actor_id": "not-a-uuid"},
        {"limit": 0},
        {"limit": 101},
        {"cursor": "%%%nope"},
        # Postgres refuses NUL in a text parameter: a 422 here, never a 500.
        {"action": "users.ban\x00"},
        {"target_type": "\x00"},
        {"target_id": "u-1\x00"},
        {"actor_id": "\x00"},
    ],
)
async def test_bad_params_are_422(
    integration_client: AsyncClient, admin_headers: Headers, params: dict[str, str | int]
) -> None:
    r = await integration_client.get(URL, params=params, headers=await admin_headers())
    assert r.status_code == 422, r.text


async def test_paging_is_stable_with_equal_timestamps(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    ann = await _admin(db_session, "Ann")
    for i in range(11):
        await _row(db_session, ann, target_id=f"u-{i}", minutes=i // 3)  # ties in threes
    h = await admin_headers()
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 4}
        if cursor is not None:
            params["cursor"] = cursor
        page = (await integration_client.get(URL, params=params, headers=h)).json()
        seen.extend(i["id"] for i in page["items"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert len(seen) == len(set(seen)) == 11


async def test_a_filter_keeps_its_cursor(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    ann = await _admin(db_session, "Ann")
    for i in range(5):
        await _row(db_session, ann, action="users.ban", minutes=i)
        await _row(db_session, ann, action="users.unban", minutes=i)
    h = await admin_headers()
    first = (
        await integration_client.get(URL, params={"action": "users.ban", "limit": 3}, headers=h)
    ).json()
    rest = (
        await integration_client.get(
            URL,
            params={"action": "users.ban", "limit": 3, "cursor": first["next_cursor"]},
            headers=h,
        )
    ).json()
    assert [i["action"] for i in first["items"] + rest["items"]] == ["users.ban"] * 5
    assert rest["next_cursor"] is None


async def test_list_query_count_is_constant(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    h = await admin_headers()

    async def _count(rows: int) -> int:
        for i in range(rows):
            await _row(db_session, await _admin(db_session, f"A{i}"), minutes=i)
        statements: list[str] = []

        def _capture(*args: object) -> None:
            statements.append(str(args[2]))

        engine = db_engine.sync_engine
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            r = await integration_client.get(URL, params={"limit": 100}, headers=h)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        assert r.status_code == 200
        return len(statements)

    few = await _count(3)
    assert few > 0
    assert few == await _count(12)
