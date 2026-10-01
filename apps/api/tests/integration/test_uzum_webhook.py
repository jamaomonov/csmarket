"""The Uzum Merchant API over HTTP, as Uzum's servers (and its manual sandbox tester) drive it:
``POST /api/v1/payments/uzum/{check,create,confirm,reverse,status}`` with Basic auth and a
JSON body carrying ``serviceId``.

Success is HTTP 200; **every** failure is HTTP 400 with ``{"status": "FAILED", "errorCode"}``
(Uzum's contract) — never a 401, 405, 422 or 500. Every credential, phone and id here is fake.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending, settle
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.uzum import service as uzum_svc
from csmarket.modules.uzum.models import UzumTransaction
from csmarket.modules.wallet.api import Leg, ensure_account, post, user_account, user_balance
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.payments_factory import make_topup

BASE = "/api/v1/payments/uzum"
SERVICE_ID = 101202
TEST_LOGIN, TEST_PASSWORD = "fake-uzum-sandbox", "fake-sandbox-password"
PROD_LOGIN, PROD_PASSWORD = "fake-uzum-cabinet", "fake-cabinet-password"
AMOUNT = Decimal(50000)
TIYIN = 5_000_000
STAMP = 1_790_000_000_000
PHONE = "998000000000"
ENDPOINTS = ("check", "create", "confirm", "reverse", "status")


@pytest.fixture(autouse=True)
def _uzum_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_UZUM_SERVICE_ID", str(SERVICE_ID))
    monkeypatch.setenv("CSMARKET_UZUM_TEST_LOGIN", TEST_LOGIN)
    monkeypatch.setenv("CSMARKET_UZUM_TEST_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("CSMARKET_UZUM_LOGIN", PROD_LOGIN)
    monkeypatch.setenv("CSMARKET_UZUM_PASSWORD", PROD_PASSWORD)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def _basic(raw: bytes) -> dict[str, str]:
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def _auth(login: str = TEST_LOGIN, password: str = TEST_PASSWORD) -> dict[str, str]:
    return _basic(f"{login}:{password}".encode())


async def _post(
    client: AsyncClient,
    endpoint: str,
    body: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> Response:
    return await client.post(
        f"{BASE}/{endpoint}", headers=_auth() if headers is None else headers, json=body
    )


async def _ok(client: AsyncClient, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    r = await _post(client, endpoint, body)
    assert r.status_code == 200, r.text
    payload: dict[str, Any] = r.json()
    return payload


async def _fail(
    client: AsyncClient,
    endpoint: str,
    body: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> int:
    r = await _post(client, endpoint, body, headers=headers)
    assert r.status_code == 400, r.text
    assert r.json()["status"] == "FAILED"
    code: int = r.json()["errorCode"]
    return code


def _check_body(number: str, key: str = "order") -> dict[str, Any]:
    return {"serviceId": SERVICE_ID, "timestamp": STAMP, "params": {key: number}}


def _create_body(
    topup: WalletTopup, trans_id: str, *, amount: int = TIYIN, key: str = "order"
) -> dict[str, Any]:
    return {
        "serviceId": SERVICE_ID,
        "timestamp": STAMP,
        "transId": trans_id,
        "params": {key: topup.number},
        "amount": amount,
    }


def _confirm_body(trans_id: str) -> dict[str, Any]:
    return {
        "serviceId": SERVICE_ID,
        "timestamp": STAMP,
        "transId": trans_id,
        "paymentSource": "UZCARD",
        "tariff": "003",
        "processingReferenceNumber": "000000",
        "phone": PHONE,
        "cardType": 2,
    }


def _trans_body(trans_id: str) -> dict[str, Any]:
    return {"serviceId": SERVICE_ID, "timestamp": STAMP, "transId": trans_id}


async def _txn(db: AsyncSession, trans_id: str) -> UzumTransaction:
    stmt = (
        select(UzumTransaction)
        .where(UzumTransaction.trans_id == trans_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _payment_status(db: AsyncSession, payment_id: str) -> str:
    return str(
        (await db.execute(select(Payment.status).where(Payment.id == payment_id))).scalar_one()
    )


async def _count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(UzumTransaction))).scalar_one())


def _install_flaky(monkeypatch: pytest.MonkeyPatch, method: str, *, fail_calls: int = 1) -> None:
    """The next ``fail_calls`` ``AsyncSession.<method>()`` calls raise, then the real one runs."""
    real = getattr(AsyncSession, method)
    calls = {"n": 0}

    async def flaky(self: AsyncSession) -> None:
        calls["n"] += 1
        if calls["n"] <= fail_calls:
            raise RuntimeError(f"simulated {method} failure")
        await real(self)

    monkeypatch.setattr(AsyncSession, method, flaky, raising=True)


# ---------- the sandbox sequences Uzum's tester runs ----------


async def test_happy_path_check_create_confirm_status(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    before = uzum_svc.now_ms()
    check = await _ok(integration_client, "check", _check_body(topup.number))
    assert check == {
        "serviceId": SERVICE_ID,
        "timestamp": check["timestamp"],
        "status": "OK",
        "data": {"amount": {"value": "50000"}},
    }
    assert check["timestamp"] >= before  # our response time, not the request's

    created = await _ok(integration_client, "create", _create_body(topup, "seq-1"))
    assert created == {
        "serviceId": SERVICE_ID,
        "transId": "seq-1",
        "status": "CREATED",
        "transTime": created["transTime"],
        "amount": TIYIN,
    }
    confirmed = await _ok(integration_client, "confirm", _confirm_body("seq-1"))
    assert confirmed == {
        "serviceId": SERVICE_ID,
        "transId": "seq-1",
        "status": "CONFIRMED",
        "confirmTime": confirmed["confirmTime"],
        "amount": TIYIN,
    }
    status = await _ok(integration_client, "status", _trans_body("seq-1"))
    assert status == {
        "serviceId": SERVICE_ID,
        "transId": "seq-1",
        "status": "CONFIRMED",
        "transTime": created["transTime"],
        "confirmTime": confirmed["confirmTime"],
        "reverseTime": None,
        "data": {},
        "amount": TIYIN,
    }
    await db_session.refresh(topup)
    assert topup.status == "succeeded"
    assert await user_balance(db_session, topup.user_id) == AMOUNT
    txn = await _txn(db_session, "seq-1")
    assert txn.payment_source == {
        "paymentSource": "UZCARD",
        "tariff": "003",
        "processingReferenceNumber": "000000",
        "phone": PHONE,
        "cardType": 2,
    }


async def test_create_then_reverse_before_confirm(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    await _ok(integration_client, "create", _create_body(topup, "seq-2"))
    reversed_ = await _ok(integration_client, "reverse", _trans_body("seq-2"))
    assert (reversed_["status"], reversed_["amount"]) == ("REVERSED", TIYIN)
    assert reversed_["reverseTime"] > 0
    txn = await _txn(db_session, "seq-2")
    assert await _payment_status(db_session, txn.payment_id) == "cancelled"
    assert await _fail(integration_client, "confirm", _confirm_body("seq-2")) == 10015
    status = await _ok(integration_client, "status", _trans_body("seq-2"))
    assert status["status"] == "REVERSED"


async def test_confirm_then_reverse_reverses_the_topup(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    await _ok(integration_client, "create", _create_body(topup, "seq-3"))
    await _ok(integration_client, "confirm", _confirm_body("seq-3"))
    assert (await _ok(integration_client, "reverse", _trans_body("seq-3")))["status"] == "REVERSED"
    await db_session.refresh(topup)
    assert topup.status == "reversed"
    assert await user_balance(db_session, topup.user_id) == 0


async def test_replays_answer_the_dedicated_codes(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    await _ok(integration_client, "create", _create_body(topup, "seq-4"))
    assert await _fail(integration_client, "create", _create_body(topup, "seq-4")) == 10010
    await _ok(integration_client, "confirm", _confirm_body("seq-4"))
    assert await _fail(integration_client, "confirm", _confirm_body("seq-4")) == 10016
    await _ok(integration_client, "reverse", _trans_body("seq-4"))
    assert await _fail(integration_client, "reverse", _trans_body("seq-4")) == 10018
    assert await _count(db_session) == 1
    assert await user_balance(db_session, topup.user_id) == 0


async def test_error_body_echoes_service_id_and_trans_id(integration_client: AsyncClient) -> None:
    r = await _post(integration_client, "confirm", _confirm_body("nope"))
    assert r.status_code == 400
    assert r.json() == {
        "status": "FAILED",
        "errorCode": 10014,
        "serviceId": SERVICE_ID,
        "transId": "nope",
    }


# ---------- the account field (R9) ----------


@pytest.mark.parametrize("key", ["order", "orderId", "order_id"])
async def test_check_and_create_accept_every_account_spelling(
    integration_client: AsyncClient, db_session: AsyncSession, key: str
) -> None:
    topup = await make_topup(db_session)
    assert (await _ok(integration_client, "check", _check_body(topup.number, key)))[
        "status"
    ] == "OK"
    created = await _ok(integration_client, "create", _create_body(topup, f"acc-{key}", key=key))
    assert created["status"] == "CREATED"
    assert (await _txn(db_session, f"acc-{key}")).account == topup.number


async def test_order_wins_over_the_other_spellings(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    body = _check_body(topup.number)
    body["params"] |= {"orderId": "T0000000", "order_id": "T0000000"}
    assert (await _ok(integration_client, "check", body))["status"] == "OK"


@pytest.mark.parametrize(
    "params",
    [{}, {"order": ""}, {"orderId": 123}, {"order_id": None}, {"account": "T1234567"}],
)
async def test_a_missing_account_is_10005(
    integration_client: AsyncClient, params: dict[str, Any]
) -> None:
    body = {"serviceId": SERVICE_ID, "timestamp": STAMP, "params": params}
    assert await _fail(integration_client, "check", body) == 10005


async def test_params_not_an_object_is_10005(integration_client: AsyncClient) -> None:
    body = {"serviceId": SERVICE_ID, "timestamp": STAMP, "params": "T1234567"}
    assert await _fail(integration_client, "check", body) == 10005


async def test_unknown_account_is_10007(integration_client: AsyncClient) -> None:
    assert await _fail(integration_client, "check", _check_body("T0000000")) == 10007


# ---------- one credit per top-up ----------


async def test_create_on_a_paid_topup_is_10008(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session, status="succeeded")
    assert await _fail(integration_client, "create", _create_body(topup, "paid")) == 10008
    assert await _count(db_session) == 0


@pytest.mark.parametrize("status", ["expired", "reversed"])
async def test_create_on_an_unpayable_topup_is_10009(
    integration_client: AsyncClient, db_session: AsyncSession, status: str
) -> None:
    topup = await make_topup(db_session, status=status)
    assert await _fail(integration_client, "create", _create_body(topup, "gone")) == 10009


async def test_create_wrong_amount_is_10011(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    body = _create_body(topup, "amount", amount=50000)  # soʻm, not tiyin
    assert await _fail(integration_client, "create", body) == 10011
    assert await _count(db_session) == 0


async def test_confirm_after_paid_elsewhere_is_10008_and_the_failure_is_kept(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    await _ok(integration_client, "create", _create_body(topup, "elsewhere"))
    other = await ensure_attempt(
        db_session, payable=await resolve(db_session, topup.number, lock=True), provider="mock"
    )
    await mark_pending(db_session, payment=other)
    await settle(db_session, payment=other, event_id="mock:elsewhere")
    await db_session.commit()

    assert await _fail(integration_client, "confirm", _confirm_body("elsewhere")) == 10008
    # Committed, not rolled back: Uzum's /status must see the transaction failed.
    txn = await _txn(db_session, "elsewhere")
    assert txn.status == "FAILED"
    assert await _payment_status(db_session, txn.payment_id) == "cancelled"
    assert (await _ok(integration_client, "status", _trans_body("elsewhere")))["status"] == "FAILED"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_reverse_spent_topup_is_10017(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    await _ok(integration_client, "create", _create_body(topup, "spent"))
    await _ok(integration_client, "confirm", _confirm_body("spent"))
    wallet = await user_account(db_session, topup.user_id)
    house = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_payments_received"
    )
    await post(
        db_session,
        kind="admin_adjust",
        legs=[Leg(wallet.id, "C", Decimal(1)), Leg(house.id, "D", Decimal(1))],
        idempotency_key="spend-1",
    )
    await db_session.commit()

    assert await _fail(integration_client, "reverse", _trans_body("spent")) == 10017
    assert (await _txn(db_session, "spent")).status == "CONFIRMED"
    assert await user_balance(db_session, topup.user_id) == AMOUNT - 1


@pytest.mark.parametrize("endpoint", ["confirm", "reverse", "status"])
async def test_unknown_trans_id_is_10014(integration_client: AsyncClient, endpoint: str) -> None:
    assert await _fail(integration_client, endpoint, _trans_body("nope")) == 10014


# ---------- auth: 10001, before the body is parsed ----------


async def test_the_production_pair_works_too(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    r = await _post(
        integration_client,
        "check",
        _check_body(topup.number),
        headers=_auth(PROD_LOGIN, PROD_PASSWORD),
    )
    assert r.status_code == 200


@pytest.mark.parametrize(("opt_in", "status"), [("false", 400), ("true", 200)])
async def test_prod_ignores_the_sandbox_pair_unless_opted_in(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    opt_in: str,
    status: int,
) -> None:
    topup = await make_topup(db_session)
    monkeypatch.setenv("CSMARKET_ENVIRONMENT", "prod")
    monkeypatch.setenv("CSMARKET_KASSA_SANDBOX_ENABLED", opt_in)
    get_settings.cache_clear()
    sandbox = await _post(integration_client, "check", _check_body(topup.number))
    assert sandbox.status_code == status
    if status == 400:
        assert sandbox.json() == {"status": "FAILED", "errorCode": 10001}
    live = await _post(
        integration_client,
        "check",
        _check_body(topup.number),
        headers=_auth(PROD_LOGIN, PROD_PASSWORD),
    )
    assert live.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer abc"},
        {"Authorization": "Basic"},
        {"Authorization": "Basic !!!not-base64!!!"},
        _basic(b"\xff\xfe:\xff"),  # not UTF-8
        _basic(b"no-colon-at-all"),
        _auth(password=PROD_PASSWORD),  # halves of two pairs
        _auth(PROD_LOGIN, TEST_PASSWORD),
        _auth(password=""),
        _auth(login=""),
        _auth(password="пароль-не-тот"),  # non-ASCII fails closed, never raises
        _auth(password=TEST_PASSWORD + "x"),
    ],
)
async def test_bad_credentials_are_10001(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    topup = await make_topup(db_session)
    r = await _post(integration_client, "create", _create_body(topup, "auth"), headers=headers)
    assert r.status_code == 400
    assert r.json() == {"status": "FAILED", "errorCode": 10001}
    assert await _count(db_session) == 0


async def test_without_any_pair_every_call_is_10001(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("LOGIN", "PASSWORD", "TEST_LOGIN", "TEST_PASSWORD"):
        monkeypatch.setenv(f"CSMARKET_UZUM_{name}", "")
    get_settings.cache_clear()
    assert (
        await _fail(integration_client, "status", _trans_body("x"), headers=_auth("", "")) == 10001
    )
    assert (
        await _fail(integration_client, "status", _trans_body("x"), headers=_basic(b":")) == 10001
    )


async def test_auth_is_checked_before_the_body_is_parsed(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        f"{BASE}/check", content=b"not json {", headers=_auth(password="wrong")
    )
    assert (r.status_code, r.json()["errorCode"]) == (400, 10001)


async def test_secrets_header_and_payment_source_never_reach_the_logs(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    with capture_logs() as logs:
        await _ok(integration_client, "create", _create_body(topup, "logs"))
        await _ok(integration_client, "confirm", _confirm_body("logs"))
        await _fail(
            integration_client, "status", _trans_body("logs"), headers=_auth(password="leaked-x")
        )
    rendered = repr(logs)
    for secret in (TEST_PASSWORD, PROD_PASSWORD, "leaked-x", _auth()["Authorization"], PHONE):
        assert secret not in rendered
    assert "UZCARD" not in rendered
    assert "user_id" not in rendered
    assert topup.user_id not in rendered
    calls = [e for e in logs if e["event"] == "uzum.callback"]
    assert [(e["endpoint"], e["code"]) for e in calls] == [
        ("create", 0),
        ("confirm", 0),
        ("status", 10001),
    ]
    assert (calls[0]["number"], calls[0]["amount_tiyin"]) == (topup.number, TIYIN)


# ---------- envelope: 10002 / 10003 / 10005 / 10006 ----------


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("content", [b"not json {", b"\xff\xfe", b"[1, 2]", b'"str"', b"null"])
async def test_a_body_that_is_not_a_json_object_is_10002(
    integration_client: AsyncClient, endpoint: str, content: bytes
) -> None:
    r = await integration_client.post(f"{BASE}/{endpoint}", headers=_auth(), content=content)
    assert r.status_code == 400
    assert r.json() == {"status": "FAILED", "errorCode": 10002}


async def test_a_deeply_nested_body_is_10002_not_500(integration_client: AsyncClient) -> None:
    """Payme review lesson: ``json.loads`` raises ``RecursionError`` on deep nesting."""
    content = b"[" * 200_000 + b"]" * 200_000
    r = await integration_client.post(f"{BASE}/check", headers=_auth(), content=content)
    assert (r.status_code, r.json()["errorCode"]) == (400, 10002)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
async def test_non_post_is_10003(
    integration_client: AsyncClient, endpoint: str, method: str
) -> None:
    r = await integration_client.request(method, f"{BASE}/{endpoint}", headers=_auth())
    assert r.status_code == 400
    assert r.json() == {"status": "FAILED", "errorCode": 10003}


@pytest.mark.parametrize("service_id", [None, 999, str(SERVICE_ID), True, float(SERVICE_ID)])
async def test_a_wrong_service_id_is_10006(
    integration_client: AsyncClient, db_session: AsyncSession, service_id: object
) -> None:
    topup = await make_topup(db_session)
    body = _check_body(topup.number) | {"serviceId": service_id}
    assert await _fail(integration_client, "check", body) == 10006


async def test_no_service_id_configured_is_10006(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CSMARKET_UZUM_SERVICE_ID", "")
    get_settings.cache_clear()
    assert await _fail(integration_client, "check", _check_body("T1234567")) == 10006


@pytest.mark.parametrize(
    ("endpoint", "body"),
    [
        ("create", {"params": {"order": "T1234567"}, "amount": TIYIN}),  # no transId
        ("create", {"transId": "", "params": {"order": "T1234567"}, "amount": TIYIN}),
        ("create", {"transId": "x" * 65, "params": {"order": "T1234567"}, "amount": TIYIN}),
        ("create", {"transId": 7, "params": {"order": "T1234567"}, "amount": TIYIN}),
        ("create", {"transId": "t", "params": {"order": "T1234567"}}),  # no amount
        ("create", {"transId": "t", "params": {"order": "T1234567"}, "amount": True}),
        ("create", {"transId": "t", "params": {"order": "T1234567"}, "amount": 1.5}),
        ("create", {"transId": "t", "params": {"order": "T1234567"}, "amount": "5000000"}),
        ("create", {"transId": "t", "amount": TIYIN}),  # no params
        ("confirm", {}),
        ("reverse", {"transId": None}),
        ("status", {"transId": ["a"]}),
    ],
)
async def test_a_missing_or_mistyped_field_is_10005(
    integration_client: AsyncClient, endpoint: str, body: dict[str, Any]
) -> None:
    payload = {"serviceId": SERVICE_ID, "timestamp": STAMP, **body}
    assert await _fail(integration_client, endpoint, payload) == 10005


# ---------- internal errors: 99999 at HTTP 400, never a 500 ----------


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_commit_failure_is_99999_not_500(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    topup = await make_topup(db_session)
    await _ok(integration_client, "create", _create_body(topup, "flaky-seed"))
    body = {
        "check": _check_body(topup.number),
        "create": _create_body(topup, "flaky"),
        "confirm": _confirm_body("flaky-seed"),
        "reverse": _trans_body("flaky-seed"),
        "status": _trans_body("flaky-seed"),
    }[endpoint]
    _install_flaky(monkeypatch, "commit")
    r = await _post(integration_client, endpoint, body)
    assert r.status_code == 400
    assert r.json()["errorCode"] == 99999
    assert r.json()["serviceId"] == SERVICE_ID


async def test_commit_and_rollback_both_failing_is_99999(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    _install_flaky(monkeypatch, "commit")
    _install_flaky(monkeypatch, "rollback")
    assert await _fail(integration_client, "create", _create_body(topup, "flaky2")) == 99999


async def test_a_failed_confirm_commit_credits_nothing(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    await _ok(integration_client, "create", _create_body(topup, "flaky3"))
    _install_flaky(monkeypatch, "commit")
    assert await _fail(integration_client, "confirm", _confirm_body("flaky3")) == 99999
    assert (await _txn(db_session, "flaky3")).status == "CREATED"
    assert await user_balance(db_session, topup.user_id) == 0


async def test_a_failed_persisting_commit_is_99999(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 10008 refusal commits the FAILED row; if that commit fails, Uzum gets 99999 and
    the row stays CREATED for the next try."""
    topup = await make_topup(db_session)
    await _ok(integration_client, "create", _create_body(topup, "flaky4"))
    other = await ensure_attempt(
        db_session, payable=await resolve(db_session, topup.number, lock=True), provider="mock"
    )
    await mark_pending(db_session, payment=other)
    await settle(db_session, payment=other, event_id="mock:flaky4")
    await db_session.commit()
    _install_flaky(monkeypatch, "commit")
    assert await _fail(integration_client, "confirm", _confirm_body("flaky4")) == 99999
    assert (await _txn(db_session, "flaky4")).status == "CREATED"


async def test_the_body_is_logged_nowhere_on_internal_error(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    await _ok(integration_client, "create", _create_body(topup, "flaky5"))
    _install_flaky(monkeypatch, "commit")
    with capture_logs() as logs:
        await _fail(integration_client, "confirm", _confirm_body("flaky5"))
    assert PHONE not in json.dumps([str(e) for e in logs])
