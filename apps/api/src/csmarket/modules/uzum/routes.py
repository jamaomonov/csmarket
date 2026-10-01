"""Uzum Bank Merchant API webhooks: ``POST /payments/uzum/{check,create,confirm,reverse,status}``.

The transport shell around :mod:`.service`: it checks HTTP Basic auth **before** reading the
body, parses the raw body itself (no request model — a 422 would not carry Uzum's error
envelope), checks ``serviceId`` and the endpoint's fields, dispatches, and renders every
outcome.

**HTTP 200 on success, HTTP 400 on any error** (Uzum's contract): bad auth (10001), bad JSON
(10002, also a body over 64 KiB or nested deeply enough to raise ``RecursionError``), a
non-POST (10003), a missing field (10005), a foreign ``serviceId`` (10006) and internal
errors (99999) are all ``{"status": "FAILED", "errorCode", ...}`` bodies at 400 — never a 401, 405, 422 or 500. The
commit sits inside the guard, so a commit failure is 99999. Log lines carry the endpoint,
the outcome code, the number and the tiyin amount — never the Authorization header, a
password, the body or ``payment_source`` (it holds the payer's phone).
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import record_kassa_rejection
from csmarket.core.request_body import KASSA_JSON_MAX_BYTES, read_capped
from csmarket.modules.uzum import service
from csmarket.modules.uzum.errors import (
    UzumError,
    access_denied,
    bad_json,
    internal_error,
    invalid_operation,
    invalid_service_id,
    missing_params,
)

router = APIRouter(prefix="/payments/uzum", tags=["uzum"])
log = get_logger("csmarket.uzum.merchant")

DbSession = Annotated[AsyncSession, Depends(db_session)]

#: The parsed request body (untrusted JSON object).
Body = dict[str, Any]
#: What a webhook answers: a success dict (HTTP 200) or an error response (HTTP 400).
Answer = dict[str, Any] | JSONResponse

#: The column holds 64 characters; Uzum's ids are UUIDs.
_MAX_TRANS_ID = 64
#: The longest account value worth echoing into a log line.
_LOG_MAX = 16
#: Uzum's codes for a body that is not JSON and for a missing / mistyped field.
_BAD_JSON = 10002
_MISSING_PARAMS = 10005
#: ``params`` keys carrying the top-up number, in order of preference (R9): our cabinet is
#: set to ``order``; Uzum has been seen sending camelCase ``orderId`` (2026-09-04).
_ACCOUNT_KEYS = ("order", "orderId", "order_id")
#: Envelope keys kept out of ``payment_source``; everything else ``/confirm`` sends is kept.
_ENVELOPE_KEYS = frozenset({"serviceId", "timestamp", "transId"})


def _is_authorized(header: str) -> bool:
    """``Basic base64("<login>:<password>")`` matching one of ``Settings.uzum_pairs()``.

    That is the production pair, plus the sandbox pair outside prod (in prod only with
    ``kassa_sandbox_enabled``). Compared as UTF-8 bytes in constant time across every usable
    pair, so a non-ASCII credential cannot raise and timing does not tell which pair matched.
    A pair with a blank half never matches; with no usable pair every call fails.
    """
    settings = get_settings()
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError):  # UnicodeDecodeError is a ValueError
        return False
    login, sep, password = decoded.partition(":")
    if not sep:
        return False
    ok = False
    for valid_login, valid_password in settings.uzum_pairs():
        login_ok = hmac.compare_digest(login.encode(), valid_login.encode())
        password_ok = hmac.compare_digest(password.encode(), valid_password.encode())
        ok |= login_ok and password_ok
    return ok


def _parse_body(raw: bytes | None) -> Body:
    """The body as a JSON object; else 10002 (also over 64 KiB, or ``RecursionError``)."""
    if raw is None:  # over 64 KiB: no Uzum call is anywhere near that
        raise bad_json()
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):  # JSONDecodeError and undecodable bytes alike
        raise bad_json() from None
    if not isinstance(payload, dict):
        raise bad_json()
    return payload


def _echo(body: Body) -> Body:
    """``serviceId`` and, when sent, ``transId`` — echoed back in an error body."""
    echo: Body = {"serviceId": body.get("serviceId")}
    if "transId" in body:
        echo["transId"] = body["transId"]
    return echo


def _service_id(body: Body) -> int:
    """Our ``uzum_service_id`` when ``serviceId`` is exactly it (an integer); else 10006."""
    configured = get_settings().uzum_service_id
    sent = body.get("serviceId")
    if configured is None or type(sent) is not int or sent != configured:
        raise invalid_service_id()
    return configured


def _trans_id(body: Body) -> str:
    """``transId``: a string of 1..64 characters; else 10005."""
    value = body.get("transId")
    if not isinstance(value, str) or not value or len(value) > _MAX_TRANS_ID:
        raise missing_params()
    return value


def _amount(body: Body) -> int:
    """``amount`` in tiyin: an integer (``bool`` excluded); else 10005."""
    value = body.get("amount")
    if isinstance(value, bool) or not isinstance(value, int):
        raise missing_params()
    return value


def _account_or_none(body: Body) -> str | None:
    """The top-up number from ``params`` (``order``, else ``orderId``, else ``order_id``)."""
    params = body.get("params")
    if not isinstance(params, dict):
        return None
    for key in _ACCOUNT_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _account(body: Body) -> str:
    """The top-up number; 10005 when ``params`` or every account spelling is missing."""
    number = _account_or_none(body)
    if number is None:
        raise missing_params()
    return number


_Handler = Callable[[AsyncSession, Body, int], Awaitable[service.Result]]


async def _check(db: AsyncSession, body: Body, _service: int) -> service.Result:
    return await service.check(db, account=_account(body))


async def _create(db: AsyncSession, body: Body, service_id: int) -> service.Result:
    return await service.create(
        db,
        service_id=service_id,
        trans_id=_trans_id(body),
        account=_account(body),
        amount=_amount(body),
    )


async def _confirm(db: AsyncSession, body: Body, _service: int) -> service.Result:
    trans_id = _trans_id(body)
    source = {key: value for key, value in body.items() if key not in _ENVELOPE_KEYS}
    return await service.confirm(db, trans_id=trans_id, payment_source=source)


async def _reverse(db: AsyncSession, body: Body, _service: int) -> service.Result:
    return await service.reverse(db, trans_id=_trans_id(body))


async def _status(db: AsyncSession, body: Body, _service: int) -> service.Result:
    return await service.status(db, trans_id=_trans_id(body))


def _fail(exc: UzumError, **echo: Any) -> JSONResponse:
    """An error body at HTTP 400 (Uzum's contract for every failure)."""
    return JSONResponse(content=exc.to_response(**echo), status_code=400)


async def _rollback_after_internal_error(db: AsyncSession, *, endpoint: str) -> None:
    """Best-effort rollback after an unexpected exception, logging either way."""
    try:
        await db.rollback()
    except Exception:
        log.exception("uzum.merchant.rollback_failed", endpoint=endpoint)
    log.exception("uzum.merchant.internal_error", endpoint=endpoint)


async def _run(
    db: AsyncSession, endpoint: str, body: Body, handler: _Handler, *, stamp: bool
) -> tuple[Answer, int]:
    """Check ``serviceId``, dispatch and commit; render any failure as an error body.

    A ``persist`` error commits what the handler wrote (a failed transaction) before
    refusing; any other error rolls back. The commit is inside the guard on purpose.
    ``stamp`` adds ``timestamp`` = our response time (``/check`` only).

    Returns:
        The answer and its outcome code (``0`` for success), for the log line.
    """
    echo = _echo(body)
    try:
        service_id = _service_id(body)
    except UzumError as exc:
        return _fail(exc, **echo), exc.code
    try:
        try:
            result = await handler(db, body, service_id)
        except UzumError as exc:
            if exc.code == _MISSING_PARAMS:  # raised only by the field extractors
                record_kassa_rejection(provider="uzum", reason="malformed")
            await (db.commit() if exc.persist else db.rollback())
            return _fail(exc, **echo), exc.code
        await db.commit()
    except Exception:  # noqa: BLE001 -- must render 99999 at HTTP 400, never a 500
        await _rollback_after_internal_error(db, endpoint=endpoint)
        error = internal_error()
        return _fail(error, **echo), error.code
    if stamp:
        return {"serviceId": service_id, "timestamp": service.now_ms(), **result}, 0
    return {"serviceId": service_id, **result}, 0


def _log_outcome(endpoint: str, body: Body, code: int) -> None:
    """One line per call: endpoint, outcome code (0 for success), number and tiyin amount."""
    number = _account_or_none(body)
    amount = body.get("amount")
    log.info(
        "uzum.callback",
        endpoint=endpoint,
        code=code,
        number=number[:_LOG_MAX] if number is not None else None,
        amount_tiyin=amount if isinstance(amount, int) and not isinstance(amount, bool) else None,
    )


async def _serve(
    request: Request, db: AsyncSession, endpoint: str, handler: _Handler, *, stamp: bool = False
) -> Answer:
    """Authenticate, then parse, then run; logs the outcome."""
    body: Body = {}
    answer: Answer
    if not _is_authorized(request.headers.get("authorization", "")):
        record_kassa_rejection(provider="uzum", reason="auth")
        error = access_denied()
        answer, code = _fail(error), error.code
    else:
        try:
            body = _parse_body(await read_capped(request, KASSA_JSON_MAX_BYTES))
        except UzumError as exc:
            if exc.code == _BAD_JSON:
                record_kassa_rejection(provider="uzum", reason="malformed")
            answer, code = _fail(exc), exc.code
        else:
            answer, code = await _run(db, endpoint, body, handler, stamp=stamp)
    _log_outcome(endpoint, body, code)
    return answer


@router.post("/check", summary="Uzum Merchant API: /check", response_model=None)
async def uzum_check(request: Request, db: DbSession) -> Answer:
    """May this top-up be paid? Answers its amount in soʻm for Uzum's app to prefill.

    Basic auth before the body is read; HTTP 400 on any error (see the module docstring).
    Writes nothing, so no ``Idempotency-Key``.
    """
    return await _serve(request, db, "check", _check, stamp=True)


@router.post("/create", summary="Uzum Merchant API: /create", response_model=None)
async def uzum_create(request: Request, db: DbSession) -> Answer:
    """Register Uzum's transaction (``CREATED``) and hold a payment attempt.

    Idempotent on Uzum's ``transId`` (a replay is 10010), so no ``Idempotency-Key``.
    """
    return await _serve(request, db, "create", _create)


@router.post("/confirm", summary="Uzum Merchant API: /confirm", response_model=None)
async def uzum_confirm(request: Request, db: DbSession) -> Answer:
    """Uzum debited the customer: credit the top-up once (a replay is 10016)."""
    return await _serve(request, db, "confirm", _confirm)


@router.post("/reverse", summary="Uzum Merchant API: /reverse", response_model=None)
async def uzum_reverse(request: Request, db: DbSession) -> Answer:
    """Cancel a held transaction or reverse a confirmed top-up (a replay is 10018)."""
    return await _serve(request, db, "reverse", _reverse)


@router.post("/status", summary="Uzum Merchant API: /status", response_model=None)
async def uzum_status(request: Request, db: DbSession) -> Answer:
    """The transaction's status and times (a plain read)."""
    return await _serve(request, db, "status", _status)


def _reject_non_post() -> JSONResponse:
    """A stray non-POST: 10003 at HTTP 400, never a 405."""
    return _fail(invalid_operation())


for _path in ("/check", "/create", "/confirm", "/reverse", "/status"):
    router.add_api_route(
        _path,
        _reject_non_post,
        methods=["GET", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )


__all__ = ["router", "uzum_check", "uzum_confirm", "uzum_create", "uzum_reverse", "uzum_status"]
