"""Email confirmation: PATCH /me sends a link, the link confirms that address only (M4b T5).

``POST /me/email/verification`` re-sends (60 s cooldown, ``email-verify`` bucket);
``POST /email/confirm`` is anonymous, idempotent and refuses a token for an address the
account no longer has.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.core.redis import get_redis
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.users.email_verify import make_token
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID

Headers = Callable[[], Awaitable[dict[str, str]]]
A, B = "a@example.uz", "b@example.uz"


async def _patch_email(c: AsyncClient, headers: dict[str, str], email: str | None) -> Any:
    r = await c.patch("/api/v1/me", json={"email": email}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _verify_rows(db: AsyncSession) -> list[EmailOutbox]:
    db.expire_all()
    rows = await db.scalars(
        select(EmailOutbox).where(EmailOutbox.kind == "verify").order_by(EmailOutbox.created_at)
    )
    return list(rows)


async def _me(db: AsyncSession) -> User:
    db.expire_all()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return user


async def _confirm(c: AsyncClient, token: str) -> Any:
    return await c.post("/api/v1/email/confirm", json={"token": token})


async def _clear_cooldown(user_id: str) -> None:
    await get_redis().delete(f"users:email_verify:cooldown:{user_id}")


async def test_a_new_email_enqueues_one_verify_letter_with_a_working_link(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    headers = await customer_headers()
    body = await _patch_email(integration_client, headers, A)
    assert (body["email"], body["email_verified"]) == (A, False)
    assert body["email_verification_sent_at"] is not None
    rows = await _verify_rows(db_session)
    assert [(r.address, r.status) for r in rows] == [(A, "pending")]
    r = await _confirm(integration_client, rows[0].payload["token"])
    assert (r.status_code, r.json()) == (200, {"email_verified": True})
    assert (await _me(db_session)).email_verified_at is not None
    me = (await integration_client.get("/api/v1/me", headers=headers)).json()
    assert me["email_verified"] is True


async def test_the_same_email_again_sends_nothing(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    headers = await customer_headers()
    await _patch_email(integration_client, headers, A)
    await _patch_email(integration_client, headers, A)
    assert len(await _verify_rows(db_session)) == 1


async def test_clearing_the_email_sends_nothing(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    headers = await customer_headers()
    body = await _patch_email(integration_client, headers, None)
    assert body["email_verification_sent_at"] is None
    assert await _verify_rows(db_session) == []


async def test_token_for_old_email_does_not_verify_new_one(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    headers = await customer_headers()
    await _patch_email(integration_client, headers, A)
    old_token = (await _verify_rows(db_session))[0].payload["token"]
    await _patch_email(integration_client, headers, B)
    r = await _confirm(integration_client, old_token)
    assert (r.status_code, r.json()["code"]) == (409, "email_token_stale")
    me = await _me(db_session)
    assert (me.email, me.email_verified_at) == (B, None)


async def test_tampered_or_expired_token_is_refused(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    headers = await customer_headers()
    await _patch_email(integration_client, headers, A)
    me_id = (await _me(db_session)).id
    token = (await _verify_rows(db_session))[0].payload["token"]
    r = await _confirm(integration_client, token[:-3] + "AAA")
    assert (r.status_code, r.json()["code"]) == (422, "email_token_invalid")
    expired = make_token(me_id, A, expires_at=clock.now() - timedelta(seconds=1))
    r = await _confirm(integration_client, expired)
    assert (r.status_code, r.json()["code"]) == (422, "email_token_expired")
    assert (await _me(db_session)).email_verified_at is None


async def test_confirm_twice_answers_twice_and_stamps_once(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    headers = await customer_headers()
    await _patch_email(integration_client, headers, A)
    token = (await _verify_rows(db_session))[0].payload["token"]
    assert (await _confirm(integration_client, token)).status_code == 200
    first = (await _me(db_session)).email_verified_at
    assert (await _confirm(integration_client, token)).status_code == 200
    assert (await _me(db_session)).email_verified_at == first


async def test_a_token_for_an_unknown_account_is_stale(integration_client: AsyncClient) -> None:
    token = make_token(
        "0190f0e0-0000-7000-8000-00000000dead", A, expires_at=clock.now() + timedelta(hours=1)
    )
    r = await _confirm(integration_client, token)
    assert (r.status_code, r.json()["code"]) == (409, "email_token_stale")


async def test_resend_waits_out_the_cooldown(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    headers = await customer_headers()
    await _patch_email(integration_client, headers, A)
    r = await integration_client.post("/api/v1/me/email/verification", headers=headers)
    assert (r.status_code, r.json()["code"]) == (429, "email_verify_cooldown")
    await _clear_cooldown((await _me(db_session)).id)
    r = await integration_client.post("/api/v1/me/email/verification", headers=headers)
    assert (r.status_code, r.json()) == (202, {"sent": True})
    rows = await _verify_rows(db_session)
    assert len(rows) == 2
    assert rows[0].payload["token"] != rows[1].payload["token"]


@pytest.mark.parametrize(
    ("email", "verified", "code"),
    [(None, False, "email_missing"), (A, True, "email_already_verified")],
    ids=["no-email", "verified"],
)
async def test_resend_needs_an_unverified_email(  # noqa: PLR0917 -- fixtures + parameters
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    email: str | None,
    verified: bool,
    code: str,
) -> None:
    headers = await customer_headers()
    me = await _me(db_session)
    me.email, me.email_verified_at = email, (clock.now() if verified else None)
    await db_session.commit()
    r = await integration_client.post("/api/v1/me/email/verification", headers=headers)
    assert (r.status_code, r.json()["code"]) == (409, code)
    assert await _verify_rows(db_session) == []


async def test_resend_replays_its_idempotency_key(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    headers = await customer_headers()
    me = await _me(db_session)
    me.email = A
    await db_session.commit()
    keyed = {**headers, "Idempotency-Key": "resend-key-0000000001"}
    first = await integration_client.post("/api/v1/me/email/verification", headers=keyed)
    again = await integration_client.post("/api/v1/me/email/verification", headers=keyed)
    assert (first.status_code, again.status_code) == (202, 202)
    assert len(await _verify_rows(db_session)) == 1


async def test_the_bucket_refuses_the_eleventh_send_in_a_minute(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers = await customer_headers()
    await _patch_email(integration_client, headers, A)
    codes = []
    for _ in range(11):
        r = await integration_client.post("/api/v1/me/email/verification", headers=headers)
        codes.append((r.status_code, r.json().get("code")))
    assert codes[:10] == [(429, "email_verify_cooldown")] * 10
    assert codes[10][0] == 429
    assert codes[10][1] != "email_verify_cooldown"


async def test_the_token_and_the_address_never_reach_the_logs(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    headers = await customer_headers()
    await _patch_email(integration_client, headers, A)
    token = (await _verify_rows(db_session))[0].payload["token"]
    await _confirm(integration_client, token)
    await _confirm(integration_client, token[:-3] + "AAA")
    out = capsys.readouterr()
    logged = caplog.text + out.out + out.err
    for leak in (token, token[:24], A):
        assert leak not in logged
