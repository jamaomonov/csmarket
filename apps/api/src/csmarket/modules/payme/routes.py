"""Payme Merchant API endpoint: ``POST /payments/payme/merchant`` (JSON-RPC 2.0).

The transport shell around :mod:`.service`: it checks HTTP Basic auth **before** reading
the body, parses the raw body itself (no request model — a 422 would read to Payme as a
transport failure), dispatches ``method`` with Payme's parameter names translated, and
renders every outcome.

**Always HTTP 200.** Payme reads any non-200 as ``-32400``, so bad auth (``-32504``), bad
JSON (``-32700``), a bad envelope (``-32600``), an unknown method (``-32601``), a non-POST
(``-32300``) and internal errors (``-32400``) are all JSON-RPC ``error`` bodies; the commit
sits inside the guard so a commit failure is ``-32400``, never a 500. Log lines carry the
method, the outcome code, the number and the amount — never the Authorization header, the
key or the body.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.logging import get_logger
from csmarket.modules.payme import service
from csmarket.modules.payme.errors import (
    PaymeError,
    bad_json,
    bad_rpc_fields,
    internal_error,
    method_not_found,
    method_not_post,
    unauthorized,
)

router = APIRouter(prefix="/payments/payme", tags=["payme"])
log = get_logger("csmarket.payme.merchant")

DbSession = Annotated[AsyncSession, Depends(db_session)]

#: A JSON-RPC response body: ``result`` or ``error``, and the request's ``id``.
RpcResponse = dict[str, Any]
#: The request's ``params`` object (untrusted JSON).
Params = dict[str, Any]

#: Payme's transaction ids are 24 hex characters; the column holds 64.
_MAX_ID = 64
#: The longest method name or account value worth echoing into a log line.
_LOG_MAX = 32


def _is_authorized(header: str) -> bool:
    """``Basic base64("<payme_login>:<key>")`` with ``key`` = ``payme_key`` or ``payme_test_key``.

    Compared as UTF-8 bytes in constant time across every configured key, so a non-ASCII
    key cannot raise and timing does not tell which key matched. A blank configured key
    never matches; with no key configured every call fails.
    """
    settings = get_settings()
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError):  # UnicodeDecodeError is a ValueError
        return False
    login, sep, key = decoded.partition(":")
    if not sep:
        return False
    login_ok = hmac.compare_digest(login.encode(), settings.payme_login.encode())
    key_ok = False
    for valid in (settings.payme_key, settings.payme_test_key):
        if valid:
            key_ok |= hmac.compare_digest(key.encode(), valid.encode())
    return login_ok and key_ok


def _req_str(params: Params, key: str) -> str:
    """A required string parameter; else ``-32600``."""
    value = params.get(key)
    if not isinstance(value, str):
        raise bad_rpc_fields()
    return value


def _req_id(params: Params) -> str:
    """Payme's transaction ``id``: a non-empty string of at most 64 characters."""
    value = _req_str(params, "id")
    if not value or len(value) > _MAX_ID:
        raise bad_rpc_fields()
    return value


def _req_int(params: Params, key: str) -> int:
    """A required integer parameter (``bool`` excluded); else ``-32600``."""
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_rpc_fields()
    return value


def _req_dict(params: Params, key: str) -> dict[str, Any]:
    """A required object parameter; else ``-32600``."""
    value = params.get(key)
    if not isinstance(value, dict):
        raise bad_rpc_fields()
    return value


_Handler = Callable[[AsyncSession, Params], Awaitable[service.Result]]

#: Method → handler translating Payme's parameter names; the ``_req_*`` extractors run at
#: call time and raise ``-32600`` for a missing or mistyped parameter.
_HANDLERS: dict[str, _Handler] = {
    "CheckPerformTransaction": lambda db, p: service.check_perform_transaction(
        db, amount=_req_int(p, "amount"), account=_req_dict(p, "account")
    ),
    "CreateTransaction": lambda db, p: service.create_transaction(
        db,
        payme_id=_req_id(p),
        time=_req_int(p, "time"),
        amount=_req_int(p, "amount"),
        account=_req_dict(p, "account"),
    ),
    "PerformTransaction": lambda db, p: service.perform_transaction(db, payme_id=_req_id(p)),
    "CancelTransaction": lambda db, p: service.cancel_transaction(
        db, payme_id=_req_id(p), reason=_req_int(p, "reason")
    ),
    "CheckTransaction": lambda db, p: service.check_transaction(db, payme_id=_req_id(p)),
    "GetStatement": lambda db, p: service.get_statement(
        db, from_ms=_req_int(p, "from"), to_ms=_req_int(p, "to")
    ),
    "SetFiscalData": lambda db, p: service.set_fiscal_data(
        db,
        payme_id=_req_id(p),
        type_=_req_str(p, "type"),
        fiscal_data=_req_dict(p, "fiscal_data"),
    ),
}


def _log_outcome(method: object, params: Params, body: RpcResponse) -> None:
    """One line per call: method, outcome code (0 for success), number and tiyin amount."""
    account = params.get("account")
    number = account.get("order") if isinstance(account, dict) else None
    amount = params.get("amount")
    error = body.get("error")
    log.info(
        "payme.rpc",
        method=method[:_LOG_MAX] if isinstance(method, str) else None,
        code=error["code"] if isinstance(error, dict) else 0,
        number=number[:_LOG_MAX] if isinstance(number, str) else None,
        amount_tiyin=amount if isinstance(amount, int) and not isinstance(amount, bool) else None,
    )


async def _rollback_after_internal_error(db: AsyncSession, *, method: str) -> None:
    """Best-effort rollback after an unexpected exception, logging either way."""
    try:
        await db.rollback()
    except Exception:
        log.exception("payme.merchant.rollback_failed", method=method[:_LOG_MAX])
    log.exception("payme.merchant.internal_error", method=method[:_LOG_MAX])


async def _run(db: AsyncSession, method: str, params: Params, req_id: object) -> RpcResponse:
    """Dispatch and commit; render a :class:`PaymeError` or any failure as an error body.

    A ``persist`` error commits what the handler wrote (a cancelled transaction) before
    refusing; any other error rolls back. The commit is inside the guard on purpose.
    """
    handler = _HANDLERS.get(method)
    if handler is None:
        return {"error": method_not_found().to_rpc_error(), "id": req_id}
    try:
        try:
            result = await handler(db, params)
        except PaymeError as exc:
            await (db.commit() if exc.persist else db.rollback())
            return {"error": exc.to_rpc_error(), "id": req_id}
        await db.commit()
    except Exception:  # noqa: BLE001 -- must render -32400 at HTTP 200, never a 500
        await _rollback_after_internal_error(db, method=method)
        return {"error": internal_error().to_rpc_error(), "id": req_id}
    return {"result": result, "id": req_id}


async def _answer(request: Request, db: AsyncSession) -> tuple[object, Params, RpcResponse]:
    """Authenticate, parse and dispatch; returns ``(method, params, body)`` for the log."""
    if not _is_authorized(request.headers.get("authorization", "")):
        return None, {}, {"error": unauthorized().to_rpc_error(), "id": None}
    try:
        payload = json.loads(await request.body())
    except ValueError:  # JSONDecodeError and undecodable bytes alike
        return None, {}, {"error": bad_json().to_rpc_error(), "id": None}
    envelope: dict[str, Any] = payload if isinstance(payload, dict) else {}
    req_id = envelope.get("id")
    method = envelope.get("method")
    params = envelope.get("params")
    if params is None:
        params = {}
    if not isinstance(method, str) or not isinstance(params, dict):
        return method, {}, {"error": bad_rpc_fields().to_rpc_error(), "id": req_id}
    return method, params, await _run(db, method, params, req_id)


@router.post("/merchant", summary="Payme Merchant API (JSON-RPC 2.0)")
async def payme_merchant(request: Request, db: DbSession) -> RpcResponse:
    """One Payme Merchant API call: ``{"method", "params", "id"}`` → ``result`` or ``error``.

    Authenticated by HTTP Basic (``Paycom:<key>``) before the body is read; always HTTP 200
    (see the module docstring). Idempotent on Payme's transaction ``id``, so no
    ``Idempotency-Key``. The request ``id`` is echoed (``null`` when absent or unparsed).
    """
    method, params, body = await _answer(request, db)
    _log_outcome(method, params, body)
    return body


def _reject_non_post() -> RpcResponse:
    """A stray non-POST: ``-32300`` at HTTP 200, never a 405."""
    return {"error": method_not_post().to_rpc_error(), "id": None}


router.add_api_route(
    "/merchant",
    _reject_non_post,
    methods=["GET", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)


__all__ = ["payme_merchant", "router"]
