"""The Payme Merchant API over HTTP, as Payme's servers (and its sandbox) drive it: one
``POST /api/v1/payments/payme/merchant`` with Basic auth and a JSON-RPC 2.0 envelope.

Payme's two mandatory sandbox sequences run whole (unconfirmed: bad auth → bad amount →
unknown account → check → create → cancel; confirmed: check → create → perform → cancel),
alongside the transport failures Payme probes for. Every response is HTTP 200: Payme reads
any other status as a transport error. Every key here is fake.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.payme.models import PaymeTransaction
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending, settle
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.wallet.api import Leg, ensure_account, post, user_account, user_balance
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.payments_factory import make_topup

URL = "/api/v1/payments/payme/merchant"
TEST_KEY = "fake-payme-sandbox-key"
PROD_KEY = "fake-payme-cabinet-key"
AMOUNT = Decimal(50000)
TIYIN = 5_000_000
TIME = 1_790_000_000_000


@pytest.fixture(autouse=True)
def _payme_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_PAYME_MERCHANT_ID", "6a1faaca155c8e168e2a0000")
    monkeypatch.setenv("CSMARKET_PAYME_TEST_KEY", TEST_KEY)
    monkeypatch.setenv("CSMARKET_PAYME_KEY", PROD_KEY)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def _basic(raw: bytes) -> dict[str, str]:
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def _auth(key: str = TEST_KEY, login: str = "Paycom") -> dict[str, str]:
    return _basic(f"{login}:{key}".encode())


def _rpc(method: str, params: dict[str, Any], req_id: object = 1) -> dict[str, Any]:
    return {"method": method, "params": params, "id": req_id}


async def _call(
    client: AsyncClient,
    method: str,
    params: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    req_id: object = 1,
) -> dict[str, Any]:
    r = await client.post(
        URL, headers=_auth() if headers is None else headers, json=_rpc(method, params, req_id)
    )
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    return body


def _code(body: dict[str, Any]) -> int:
    code: int = body["error"]["code"]
    return code


def _create_params(topup: WalletTopup, payme_id: str, amount: int = TIYIN) -> dict[str, Any]:
    return {"id": payme_id, "time": TIME, "amount": amount, "account": {"order": topup.number}}


async def _txn(db: AsyncSession, payme_id: str) -> PaymeTransaction:
    stmt = (
        select(PaymeTransaction)
        .where(PaymeTransaction.payme_id == payme_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _payment_status(db: AsyncSession, payment_id: str) -> str:
    return str(
        (await db.execute(select(Payment.status).where(Payment.id == payment_id))).scalar_one()
    )


async def _count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(PaymeTransaction))).scalar_one())


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


# ---------- Payme's sandbox sequences ----------


async def test_sandbox_sequence_unconfirmed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    account = {"order": topup.number}

    bad = await _call(
        integration_client,
        "CheckPerformTransaction",
        {"amount": TIYIN, "account": account},
        headers=_auth(key="wrong-key"),
    )
    assert (_code(bad), bad["id"]) == (-32504, None)
    wrong_amount = await _call(
        integration_client, "CheckPerformTransaction", {"amount": TIYIN + 1, "account": account}
    )
    assert _code(wrong_amount) == -31001
    unknown = await _call(
        integration_client,
        "CheckPerformTransaction",
        {"amount": TIYIN, "account": {"order": "T0000000"}},
    )
    assert (_code(unknown), unknown["error"]["data"]) == (-31050, "order")
    allowed = await _call(
        integration_client, "CheckPerformTransaction", {"amount": TIYIN, "account": account}
    )
    assert allowed == {"result": {"allow": True}, "id": 1}

    created = (await _call(integration_client, "CreateTransaction", _create_params(topup, "seq1")))[
        "result"
    ]
    assert (created["state"], created["create_time"]) == (1, TIME)
    cancelled = (await _call(integration_client, "CancelTransaction", {"id": "seq1", "reason": 1}))[
        "result"
    ]
    assert (cancelled["state"], cancelled["transaction"]) == (-1, created["transaction"])
    assert cancelled["cancel_time"] > 0

    txn = await _txn(db_session, "seq1")
    assert await _payment_status(db_session, txn.payment_id) == "cancelled"
    await db_session.refresh(topup)
    assert topup.status == "pending"


async def test_sandbox_sequence_confirmed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    check = await _call(
        integration_client,
        "CheckPerformTransaction",
        {"amount": TIYIN, "account": {"order": topup.number}},
    )
    assert check["result"] == {"allow": True}
    created = await _call(integration_client, "CreateTransaction", _create_params(topup, "seq2"))
    assert created["result"]["state"] == 1
    performed = (await _call(integration_client, "PerformTransaction", {"id": "seq2"}))["result"]
    assert performed["state"] == 2
    assert performed["perform_time"] > 0
    await db_session.refresh(topup)
    assert topup.status == "succeeded"
    assert await user_balance(db_session, topup.user_id) == AMOUNT

    checked = (await _call(integration_client, "CheckTransaction", {"id": "seq2"}))["result"]
    assert (checked["state"], checked["perform_time"]) == (2, performed["perform_time"])

    reversed_ = (await _call(integration_client, "CancelTransaction", {"id": "seq2", "reason": 5}))[
        "result"
    ]
    assert reversed_["state"] == -2
    await db_session.refresh(topup)
    assert topup.status == "reversed"
    assert await user_balance(db_session, topup.user_id) == 0
    txn = await _txn(db_session, "seq2")
    assert (txn.state, txn.reason) == (-2, 5)
    assert await _payment_status(db_session, txn.payment_id) == "refunded"


async def test_replay_create_perform_cancel_is_idempotent(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    for method, params in (
        ("CreateTransaction", _create_params(topup, "replay")),
        ("PerformTransaction", {"id": "replay"}),
        ("CancelTransaction", {"id": "replay", "reason": 5}),
    ):
        first = await _call(integration_client, method, params)
        second = await _call(integration_client, method, params)
        assert "result" in first
        assert first == second
    assert await _count(db_session) == 1
    assert await user_balance(db_session, topup.user_id) == 0


# ---------- one credit per top-up ----------


async def test_create_on_a_paid_topup_is_31051(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session, status="succeeded")
    body = await _call(integration_client, "CreateTransaction", _create_params(topup, "paid"))
    assert (_code(body), body["error"]["data"]) == (-31051, "order")
    assert await _count(db_session) == 0


async def test_perform_after_paid_elsewhere_is_31008_and_the_cancel_is_kept(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    await _call(integration_client, "CreateTransaction", _create_params(topup, "elsewhere"))
    other = await ensure_attempt(
        db_session, payable=await resolve(db_session, topup.number, lock=True), provider="mock"
    )
    await mark_pending(db_session, payment=other)
    await settle(db_session, payment=other, event_id="mock:elsewhere")
    await db_session.commit()

    body = await _call(integration_client, "PerformTransaction", {"id": "elsewhere"})
    assert _code(body) == -31008
    # Committed, not rolled back: Payme must see the transaction cancelled.
    txn = await _txn(db_session, "elsewhere")
    assert (txn.state, txn.reason) == (-1, 3)
    assert await _payment_status(db_session, txn.payment_id) == "cancelled"
    checked = (await _call(integration_client, "CheckTransaction", {"id": "elsewhere"}))["result"]
    assert (checked["state"], checked["reason"]) == (-1, 3)
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_cancel_of_a_spent_topup_is_31007(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    await _call(integration_client, "CreateTransaction", _create_params(topup, "spent"))
    await _call(integration_client, "PerformTransaction", {"id": "spent"})
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

    body = await _call(integration_client, "CancelTransaction", {"id": "spent", "reason": 5})
    assert _code(body) == -31007
    assert (await _txn(db_session, "spent")).state == 2
    assert await user_balance(db_session, topup.user_id) == AMOUNT - 1


# ---------- the other methods over HTTP ----------


async def test_get_statement_and_set_fiscal_data(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    await _call(integration_client, "CreateTransaction", _create_params(topup, "stmt"))
    statement = await _call(integration_client, "GetStatement", {"from": TIME, "to": TIME})
    (row,) = statement["result"]["transactions"]
    assert (row["id"], row["amount"], row["account"]) == ("stmt", TIYIN, {"order": topup.number})

    receipt = {"receipt_id": 7, "status_code": 0}
    fiscal = await _call(
        integration_client,
        "SetFiscalData",
        {"id": "stmt", "type": "PERFORM", "fiscal_data": receipt},
    )
    assert fiscal["result"] == {"success": True}
    assert (await _txn(db_session, "stmt")).fiscal_data == {"PERFORM": receipt}
    unknown = await _call(
        integration_client, "SetFiscalData", {"id": "nope", "type": "PERFORM", "fiscal_data": {}}
    )
    assert _code(unknown) == -32001


async def test_unknown_transaction_is_31003(integration_client: AsyncClient) -> None:
    for method in ("PerformTransaction", "CheckTransaction"):
        assert _code(await _call(integration_client, method, {"id": "nope"})) == -31003


# ---------- auth: -32504 at HTTP 200 ----------


async def test_the_production_key_works_too(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    body = await _call(
        integration_client,
        "CheckPerformTransaction",
        {"amount": TIYIN, "account": {"order": topup.number}},
        headers=_auth(key=PROD_KEY),
    )
    assert body["result"] == {"allow": True}


@pytest.mark.parametrize(("opt_in", "allowed"), [("false", False), ("true", True)])
async def test_prod_ignores_the_test_key_unless_opted_in(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    opt_in: str,
    allowed: bool,
) -> None:
    topup = await make_topup(db_session)
    monkeypatch.setenv("CSMARKET_ENVIRONMENT", "prod")
    monkeypatch.setenv("CSMARKET_KASSA_SANDBOX_ENABLED", opt_in)
    get_settings.cache_clear()
    params = {"amount": TIYIN, "account": {"order": topup.number}}
    sandbox = await _call(integration_client, "CheckPerformTransaction", params)
    if allowed:
        assert sandbox["result"] == {"allow": True}
    else:
        assert _code(sandbox) == -32504
    live = await _call(
        integration_client, "CheckPerformTransaction", params, headers=_auth(key=PROD_KEY)
    )
    assert live["result"] == {"allow": True}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer abc"},
        {"Authorization": "Basic"},
        {"Authorization": "Basic !!!not-base64!!!"},
        _basic(b"\xff\xfe:\xff"),  # not UTF-8
        _basic(b"Paycom-no-colon"),
        _auth(login="Merchant"),
        _auth(key=""),
        _auth(key="ключ-не-тот"),  # non-ASCII fails closed, never raises
        _auth(key=TEST_KEY + "x"),
    ],
)
async def test_bad_credentials_are_32504(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    topup = await make_topup(db_session)
    body = await _call(
        integration_client, "CreateTransaction", _create_params(topup, "auth"), headers=headers
    )
    assert body == {"error": body["error"], "id": None}
    assert _code(body) == -32504
    assert await _count(db_session) == 0


async def test_without_any_key_every_call_is_32504(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CSMARKET_PAYME_KEY", "")
    monkeypatch.setenv("CSMARKET_PAYME_TEST_KEY", "")
    get_settings.cache_clear()
    body = await _call(integration_client, "CheckTransaction", {"id": "x"}, headers=_auth(key=""))
    assert _code(body) == -32504


async def test_auth_is_checked_before_the_body_is_parsed(integration_client: AsyncClient) -> None:
    r = await integration_client.post(URL, content=b"not json {", headers=_auth(key="wrong"))
    assert r.json()["error"]["code"] == -32504


async def test_the_key_and_the_header_never_reach_the_logs(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    with capture_logs() as logs:
        await _call(integration_client, "CreateTransaction", _create_params(topup, "logs"))
        await _call(integration_client, "PerformTransaction", {"id": "logs"})
        await _call(
            integration_client, "CheckTransaction", {"id": "logs"}, headers=_auth(key="leaked-x")
        )
    rendered = repr(logs)
    for secret in (TEST_KEY, PROD_KEY, "leaked-x", _auth()["Authorization"]):
        assert secret not in rendered
    assert "user_id" not in rendered
    assert topup.user_id not in rendered
    calls = [e for e in logs if e["event"] == "payme.rpc"]
    assert [(e["method"], e["code"]) for e in calls] == [
        ("CreateTransaction", 0),
        ("PerformTransaction", 0),
        (None, -32504),
    ]
    assert (calls[0]["number"], calls[0]["amount_tiyin"]) == (topup.number, TIYIN)


# ---------- envelope: -32700 / -32600 / -32601 ----------


async def test_a_body_over_64_kib_is_32700(integration_client: AsyncClient) -> None:
    envelope = {"method": "CheckTransaction", "params": {"id": "nope"}, "id": 7}
    over = json.dumps({**envelope, "pad": "a" * (64 * 1024)}).encode()
    r = await integration_client.post(URL, headers=_auth(), content=over)
    assert r.json() == {"error": r.json()["error"], "id": None}
    assert r.json()["error"]["code"] == -32700
    near = json.dumps({**envelope, "pad": "a" * (60 * 1024)}).encode()
    r = await integration_client.post(URL, headers=_auth(), content=near)
    assert (r.json()["error"]["code"], r.json()["id"]) == (-31003, 7)


async def test_non_json_body_is_32700(integration_client: AsyncClient) -> None:
    for content in (b"not json at all {", b"\xff\xfe"):
        r = await integration_client.post(URL, headers=_auth(), content=content)
        assert r.status_code == 200
        assert r.json() == {"error": r.json()["error"], "id": None}
        assert r.json()["error"]["code"] == -32700


@pytest.mark.parametrize(
    "payload",
    [
        [1, 2],
        "string",
        {"params": {}, "id": 5},
        {"method": 7, "id": 5},
        {"method": "X", "params": []},
    ],
)
async def test_a_bad_envelope_is_32600(integration_client: AsyncClient, payload: object) -> None:
    r = await integration_client.post(URL, headers=_auth(), json=payload)
    assert r.json()["error"]["code"] == -32600


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("CheckPerformTransaction", {"account": {"order": "T1234567"}}),
        ("CheckPerformTransaction", {"amount": True, "account": {"order": "T1234567"}}),
        ("CheckPerformTransaction", {"amount": 1.5, "account": {"order": "T1234567"}}),
        ("CheckPerformTransaction", {"amount": 1, "account": "T1234567"}),
        ("CreateTransaction", {"id": "", "time": TIME, "amount": 1, "account": {}}),
        ("CreateTransaction", {"id": "x" * 65, "time": TIME, "amount": 1, "account": {}}),
        ("CreateTransaction", {"id": 123, "time": TIME, "amount": 1, "account": {}}),
        ("CancelTransaction", {"id": "a"}),
        ("GetStatement", {"from": 1}),
        ("SetFiscalData", {"id": "a", "type": "PERFORM", "fiscal_data": "x"}),
    ],
)
async def test_a_missing_or_mistyped_param_is_32600(
    integration_client: AsyncClient, method: str, params: dict[str, Any]
) -> None:
    body = await _call(integration_client, method, params, req_id="rpc-7")
    assert (_code(body), body["id"]) == (-32600, "rpc-7")


async def test_unknown_method_is_32601_and_the_id_is_echoed(
    integration_client: AsyncClient,
) -> None:
    body = await _call(integration_client, "NoSuchMethod", {}, req_id="rpc-abc-123")
    assert (_code(body), body["id"]) == (-32601, "rpc-abc-123")
    r = await integration_client.post(
        URL, headers=_auth(), json={"method": "NoSuchMethod", "params": None, "id": 3}
    )
    assert r.json()["error"]["code"] == -32601


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_non_post_is_32300(integration_client: AsyncClient, method: str) -> None:
    r = await integration_client.request(method, URL, headers=_auth())
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32300


# ---------- internal errors: -32400 at HTTP 200, never a 500 ----------


async def test_commit_failure_is_32400_not_500(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    _install_flaky(monkeypatch, "commit")
    body = await _call(integration_client, "CreateTransaction", _create_params(topup, "flaky"))
    assert _code(body) == -32400
    assert await _count(db_session) == 0


async def test_commit_and_rollback_both_failing_is_32400(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    _install_flaky(monkeypatch, "commit")
    _install_flaky(monkeypatch, "rollback")
    body = await _call(integration_client, "CreateTransaction", _create_params(topup, "flaky2"))
    assert _code(body) == -32400


async def test_a_failed_perform_commit_credits_nothing(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    await _call(integration_client, "CreateTransaction", _create_params(topup, "flaky3"))
    _install_flaky(monkeypatch, "commit")
    assert _code(await _call(integration_client, "PerformTransaction", {"id": "flaky3"})) == -32400
    assert (await _txn(db_session, "flaky3")).state == 1
    assert await user_balance(db_session, topup.user_id) == 0
