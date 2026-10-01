"""The Click Shop API callbacks over HTTP, as Click's servers drive them: form-encoded
``POST /api/v1/payments/click/{prepare,complete}`` signed with an MD5 ``sign_string``.

Every response, success or failure, is HTTP 200. Every key here is fake.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from decimal import Decimal

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.click.models import ClickTransaction
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending, settle
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.wallet.api import user_balance
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.payments_factory import make_topup

PREPARE_URL = "/api/v1/payments/click/prepare"
COMPLETE_URL = "/api/v1/payments/click/complete"

SERVICE_ID = "108149"
SECRET = "fake-click-secret"
AMOUNT = Decimal(50000)
AMOUNT_STR = "50000.00"
PREPARE_TIME = "2026-10-01 10:00:00"
COMPLETE_TIME = "2026-10-01 10:05:00"


@pytest.fixture(autouse=True)
def _click_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_CLICK_MERCHANT_ID", "5000")
    monkeypatch.setenv("CSMARKET_CLICK_SERVICE_ID", SERVICE_ID)
    monkeypatch.setenv("CSMARKET_CLICK_SECRET_KEY", SECRET)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def _md5(*parts: str) -> str:
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _prepare_body(
    *,
    click_trans_id: str,
    merchant_trans_id: str,
    amount: str = AMOUNT_STR,
    action: str = "0",
    error: str = "0",
    service_id: str = SERVICE_ID,
    secret: str = SECRET,
) -> dict[str, str]:
    return {
        "click_trans_id": click_trans_id,
        "service_id": service_id,
        "click_paydoc_id": "5001",
        "merchant_trans_id": merchant_trans_id,
        "amount": amount,
        "action": action,
        "error": error,
        "error_note": "Success" if error == "0" else "cancelled",
        "sign_time": PREPARE_TIME,
        "sign_string": _md5(
            click_trans_id, service_id, secret, merchant_trans_id, amount, action, PREPARE_TIME
        ),
    }


def _complete_body(
    *,
    click_trans_id: str,
    merchant_trans_id: str,
    merchant_prepare_id: str,
    amount: str = AMOUNT_STR,
    action: str = "1",
    error: str = "0",
    service_id: str = SERVICE_ID,
    secret: str = SECRET,
) -> dict[str, str]:
    return {
        "click_trans_id": click_trans_id,
        "service_id": service_id,
        "click_paydoc_id": "5001",
        "merchant_trans_id": merchant_trans_id,
        "merchant_prepare_id": merchant_prepare_id,
        "amount": amount,
        "action": action,
        "error": error,
        "error_note": "Success" if error == "0" else "cancelled",
        "sign_time": COMPLETE_TIME,
        "sign_string": _md5(
            click_trans_id,
            service_id,
            secret,
            merchant_trans_id,
            merchant_prepare_id,
            amount,
            action,
            COMPLETE_TIME,
        ),
    }


async def _post(client: AsyncClient, url: str, data: dict[str, str]) -> dict[str, object]:
    r = await client.post(url, data=data)
    assert r.status_code == 200
    body: dict[str, object] = r.json()
    return body


async def _prepared(client: AsyncClient, topup: WalletTopup, trans_id: str) -> str:
    body = await _post(
        client, PREPARE_URL, _prepare_body(click_trans_id=trans_id, merchant_trans_id=topup.number)
    )
    assert body["error"] == 0
    return str(body["merchant_prepare_id"])


async def _txn(db: AsyncSession, trans_id: str) -> ClickTransaction:
    stmt = (
        select(ClickTransaction)
        .where(ClickTransaction.click_trans_id == int(trans_id))
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _payment_status(db: AsyncSession, payment_id: str) -> str:
    stmt = select(Payment.status).where(Payment.id == payment_id)
    return str((await db.execute(stmt)).scalar_one())


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


# ---------- happy path ----------


async def test_prepare_then_complete_credits_the_balance(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    prepared = await _post(
        integration_client,
        PREPARE_URL,
        _prepare_body(click_trans_id="9001", merchant_trans_id=topup.number),
    )
    assert (prepared["error"], prepared["error_note"]) == (0, "Success")
    assert prepared["click_trans_id"] == 9001
    assert prepared["merchant_trans_id"] == topup.number
    assert isinstance(prepared["merchant_prepare_id"], int)

    completed = await _post(
        integration_client,
        COMPLETE_URL,
        _complete_body(
            click_trans_id="9001",
            merchant_trans_id=topup.number,
            merchant_prepare_id=str(prepared["merchant_prepare_id"]),
        ),
    )
    assert (completed["error"], completed["error_note"]) == (0, "Success")
    assert completed["merchant_confirm_id"] == prepared["merchant_prepare_id"]
    await db_session.refresh(topup)
    assert topup.status == "succeeded"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_a_replayed_complete_is_minus4_and_credits_once(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    prepare_id = await _prepared(integration_client, topup, "9030")
    body = _complete_body(
        click_trans_id="9030", merchant_trans_id=topup.number, merchant_prepare_id=prepare_id
    )
    assert (await _post(integration_client, COMPLETE_URL, body))["error"] == 0
    assert (await _post(integration_client, COMPLETE_URL, body))["error"] == -4
    assert await user_balance(db_session, topup.user_id) == AMOUNT


# ---------- one credit per top-up ----------


async def test_a_second_prepare_on_a_paid_topup_is_minus4(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session, status="succeeded")
    body = await _post(
        integration_client,
        PREPARE_URL,
        _prepare_body(click_trans_id="9040", merchant_trans_id=topup.number),
    )
    assert body == {
        "error": -4,
        "error_note": "Already paid",
        "click_trans_id": "9040",
        "merchant_trans_id": topup.number,
    }


async def test_a_complete_after_the_topup_was_paid_elsewhere_is_minus4(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    prepare_id = await _prepared(integration_client, topup, "9041")
    other = await ensure_attempt(
        db_session, payable=await resolve(db_session, topup.number, lock=True), provider="mock"
    )
    await mark_pending(db_session, payment=other)
    await settle(db_session, payment=other, event_id="mock:elsewhere")
    await db_session.commit()

    body = await _post(
        integration_client,
        COMPLETE_URL,
        _complete_body(
            click_trans_id="9041", merchant_trans_id=topup.number, merchant_prepare_id=prepare_id
        ),
    )
    assert (body["error"], body["error_note"]) == (-4, "Already paid")
    # Committed, not rolled back: Click must see the transaction cancelled.
    txn = await _txn(db_session, "9041")
    assert txn.status == "CANCELLED"
    assert await _payment_status(db_session, txn.payment_id) == "cancelled"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


# ---------- signature ----------


@pytest.mark.parametrize(
    "tamper", [{"sign_string": "0" * 32}, {"amount": "1.00"}, {"merchant_trans_id": "T1111111"}]
)
async def test_prepare_with_a_bad_signature_is_minus1(
    integration_client: AsyncClient, db_session: AsyncSession, tamper: dict[str, str]
) -> None:
    topup = await make_topup(db_session)
    body = {**_prepare_body(click_trans_id="9002", merchant_trans_id=topup.number), **tamper}
    resp = await _post(integration_client, PREPARE_URL, body)
    assert (resp["error"], resp["error_note"]) == (-1, "SIGN CHECK FAILED!")
    assert (await db_session.execute(select(ClickTransaction))).first() is None


async def test_prepare_for_another_service_is_minus1(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    body = _prepare_body(
        click_trans_id="9003", merchant_trans_id=topup.number, service_id="108150", secret=SECRET
    )
    assert (await _post(integration_client, PREPARE_URL, body))["error"] == -1


async def test_without_a_secret_every_call_is_minus1(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    monkeypatch.setenv("CSMARKET_CLICK_SECRET_KEY", "")
    get_settings.cache_clear()
    body = _prepare_body(click_trans_id="9004", merchant_trans_id=topup.number, secret="")
    assert (await _post(integration_client, PREPARE_URL, body))["error"] == -1


async def test_complete_with_a_bad_signature_is_minus1(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    prepare_id = await _prepared(integration_client, topup, "9020")
    body = _complete_body(
        click_trans_id="9020", merchant_trans_id=topup.number, merchant_prepare_id=prepare_id
    )
    body["sign_string"] = "0" * 32
    assert (await _post(integration_client, COMPLETE_URL, body))["error"] == -1
    assert (await _txn(db_session, "9020")).status == "PREPARED"


async def test_complete_for_another_service_is_minus1(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    prepare_id = await _prepared(integration_client, topup, "9021")
    body = _complete_body(
        click_trans_id="9021",
        merchant_trans_id=topup.number,
        merchant_prepare_id=prepare_id,
        service_id="999999",
    )
    assert (await _post(integration_client, COMPLETE_URL, body))["error"] == -1


async def test_the_sign_string_and_the_secret_never_reach_the_logs(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    body = _prepare_body(click_trans_id="9050", merchant_trans_id=topup.number)
    with capture_logs() as logs:
        await _post(integration_client, PREPARE_URL, body)
        await _post(integration_client, PREPARE_URL, {**body, "sign_string": "f" * 32})
    rendered = repr(logs)
    assert body["sign_string"] not in rendered
    assert "f" * 32 not in rendered
    assert SECRET not in rendered
    outcomes = [e for e in logs if e["event"] == "click.callback"]
    assert [e["error"] for e in outcomes] == [0, -1]
    assert outcomes[0]["number"] == topup.number
    assert outcomes[0]["amount"] == AMOUNT_STR
    assert "user_id" not in outcomes[0]


# ---------- business errors ----------


async def test_complete_service_error_is_echoed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    prepare_id = await _prepared(integration_client, topup, "9022")
    body = _complete_body(
        click_trans_id="9022",
        merchant_trans_id=topup.number,
        merchant_prepare_id=prepare_id,
        amount="49999.00",
    )
    assert await _post(integration_client, COMPLETE_URL, body) == {
        "error": -2,
        "error_note": "Incorrect parameter amount",
        "click_trans_id": "9022",
        "merchant_trans_id": topup.number,
    }


async def test_prepare_wrong_action_is_minus3(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    body = _prepare_body(click_trans_id="9005", merchant_trans_id=topup.number, action="5")
    resp = await _post(integration_client, PREPARE_URL, body)
    assert (resp["error"], resp["error_note"]) == (-3, "Action not found")


async def test_complete_wrong_action_is_minus3(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    prepare_id = await _prepared(integration_client, topup, "9006")
    body = _complete_body(
        click_trans_id="9006",
        merchant_trans_id=topup.number,
        merchant_prepare_id=prepare_id,
        action="0",
    )
    assert (await _post(integration_client, COMPLETE_URL, body))["error"] == -3


async def test_prepare_wrong_amount_is_minus2(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    body = _prepare_body(click_trans_id="9007", merchant_trans_id=topup.number, amount="5000000")
    assert (await _post(integration_client, PREPARE_URL, body))["error"] == -2


async def test_prepare_unknown_account_is_minus5(integration_client: AsyncClient) -> None:
    body = _prepare_body(click_trans_id="9008", merchant_trans_id="T0000000")
    resp = await _post(integration_client, PREPARE_URL, body)
    assert (resp["error"], resp["error_note"]) == (-5, "User does not exist")


# ---------- negative inbound error → cancel + -9 ----------


async def test_prepare_negative_inbound_error_cancels_and_returns_minus9(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    await _prepared(integration_client, topup, "9009")
    body = _prepare_body(click_trans_id="9009", merchant_trans_id=topup.number, error="-5000")
    resp = await _post(integration_client, PREPARE_URL, body)
    assert (resp["error"], resp["error_note"]) == (-9, "Transaction cancelled")
    txn = await _txn(db_session, "9009")
    assert txn.status == "CANCELLED"
    assert await _payment_status(db_session, txn.payment_id) == "cancelled"


async def test_complete_negative_inbound_error_cancels_and_returns_minus9(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    prepare_id = await _prepared(integration_client, topup, "9010")
    body = _complete_body(
        click_trans_id="9010",
        merchant_trans_id=topup.number,
        merchant_prepare_id=prepare_id,
        error="-1",
    )
    assert (await _post(integration_client, COMPLETE_URL, body))["error"] == -9
    assert (await _txn(db_session, "9010")).status == "CANCELLED"
    await db_session.refresh(topup)
    assert topup.status == "pending"


# ---------- internal errors: -7 at HTTP 200, never a 500 ----------


async def test_prepare_commit_failure_is_minus7(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    _install_flaky(monkeypatch, "commit")
    body = _prepare_body(click_trans_id="9012", merchant_trans_id=topup.number)
    resp = await _post(integration_client, PREPARE_URL, body)
    assert (resp["error"], resp["error_note"]) == (-7, "Failed to update user")
    assert (await db_session.execute(select(ClickTransaction))).first() is None


async def test_prepare_commit_and_rollback_both_fail_is_minus7(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    _install_flaky(monkeypatch, "commit")
    _install_flaky(monkeypatch, "rollback")
    body = _prepare_body(click_trans_id="9013", merchant_trans_id=topup.number)
    assert (await _post(integration_client, PREPARE_URL, body))["error"] == -7


async def test_complete_commit_failure_is_minus7(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    prepare_id = await _prepared(integration_client, topup, "9014")
    _install_flaky(monkeypatch, "commit")
    body = _complete_body(
        click_trans_id="9014", merchant_trans_id=topup.number, merchant_prepare_id=prepare_id
    )
    assert (await _post(integration_client, COMPLETE_URL, body))["error"] == -7
    assert (await _txn(db_session, "9014")).status == "PREPARED"
    assert await user_balance(db_session, topup.user_id) == 0


# ---------- malformed requests: -8 ----------


async def test_prepare_missing_field_is_minus8(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    body = _prepare_body(click_trans_id="9015", merchant_trans_id=topup.number)
    del body["sign_time"]
    resp = await _post(integration_client, PREPARE_URL, body)
    assert resp == {
        "error": -8,
        "error_note": "Error in request from click",
        "click_trans_id": "9015",
        "merchant_trans_id": topup.number,
    }


async def test_prepare_non_numeric_click_trans_id_is_minus8(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    body = _prepare_body(click_trans_id="not-a-number", merchant_trans_id=topup.number)
    assert (await _post(integration_client, PREPARE_URL, body))["error"] == -8


async def test_complete_missing_merchant_prepare_id_is_minus8(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    topup = await make_topup(db_session)
    prepare_id = await _prepared(integration_client, topup, "9016")
    body = _complete_body(
        click_trans_id="9016", merchant_trans_id=topup.number, merchant_prepare_id=prepare_id
    )
    del body["merchant_prepare_id"]
    assert (await _post(integration_client, COMPLETE_URL, body))["error"] == -8


@pytest.mark.parametrize("url", [PREPARE_URL, COMPLETE_URL])
async def test_a_json_body_is_minus8(integration_client: AsyncClient, url: str) -> None:
    r = await integration_client.post(url, json={"click_trans_id": "1"})
    assert r.status_code == 200
    assert r.json()["error"] == -8


@pytest.mark.parametrize("url", [PREPARE_URL, COMPLETE_URL])
async def test_malformed_multipart_body_is_minus8(
    integration_client: AsyncClient, url: str
) -> None:
    r = await integration_client.post(
        url,
        headers={"content-type": "multipart/form-data; boundary=X"},
        content=b"not a valid multipart body at all",
    )
    assert r.status_code == 200
    assert r.json() == {"error": -8, "error_note": "Error in request from click"}


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
@pytest.mark.parametrize("url", [PREPARE_URL, COMPLETE_URL])
async def test_non_post_is_minus8(integration_client: AsyncClient, url: str, method: str) -> None:
    r = await integration_client.request(method, url)
    assert r.status_code == 200
    assert r.json() == {"error": -8, "error_note": "Error in request from click"}


async def test_a_charset_on_the_content_type_is_fine(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from urllib.parse import urlencode

    topup = await make_topup(db_session)
    body = _prepare_body(click_trans_id="9060", merchant_trans_id=topup.number)
    r = await integration_client.post(
        PREPARE_URL,
        content=urlencode(body).encode(),
        headers={"content-type": "application/x-www-form-urlencoded; charset=UTF-8"},
    )
    assert r.json()["error"] == 0


@pytest.mark.parametrize(
    "content",
    [
        b"a=" + b"x" * 9000,  # over the size cap
        b"click_trans_id=\xff\xfe",  # not UTF-8
        b"&".join(b"f%d=1" % i for i in range(40)),  # too many fields
    ],
)
async def test_an_oversized_or_garbled_body_is_minus8(
    integration_client: AsyncClient, content: bytes
) -> None:
    r = await integration_client.post(
        PREPARE_URL,
        content=content,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    assert r.json() == {"error": -8, "error_note": "Error in request from click"}
