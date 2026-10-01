"""Click Shop API callbacks: ``POST /payments/click/prepare`` and ``/complete``.

Click posts ``application/x-www-form-urlencoded`` bodies signed with an MD5 ``sign_string``
(:mod:`.signature`). This module parses the body itself with the standard library (no
request model: a missing field is our ``-8``, never FastAPI's 422; and no
``python-multipart`` dependency — Click never sends multipart), verifies the signature
**before** any business logic, checks ``action``, applies Click's negative-inbound-``error`` rule (cancel,
answer ``-9``), dispatches to :mod:`.service` and renders every outcome.

**Always HTTP 200.** Click reads any other status as a transport failure, so errors are
``{"error": <int>, "error_note": <str>, ...echo}`` bodies; the commit sits inside the guard
so a commit failure is ``-7``, never a 500. A stray non-POST is ``-8``. Log lines carry the
method, the outcome code, the number and the amount — never the sign string or the secret.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.logging import get_logger
from csmarket.core.metrics import record_kassa_rejection
from csmarket.modules.click import service, signature
from csmarket.modules.click.errors import (
    ClickError,
    action_not_found,
    bad_request,
    failed_to_update,
    sign_check_failed,
    transaction_cancelled,
)

router = APIRouter(prefix="/payments/click", tags=["click"])
log = get_logger("csmarket.click.webhook")

DbSession = Annotated[AsyncSession, Depends(db_session)]

#: The longest account value worth echoing into a log line (a top-up number is 8).
_LOG_NUMBER_MAX = 16
#: A Click body is ~11 short fields; anything bigger is not Click.
_MAX_BODY_BYTES = 8 * 1024
_MAX_FIELDS = 32
#: Click's codes for a wrong signature or service id, and for a malformed request.
_SIGN_CHECK_FAILED = -1
_BAD_REQUEST = -8

#: The parsed body: field name → the raw string Click sent (the last one if repeated).
Form = Mapping[str, str]


def _count_rejection(exc: ClickError) -> None:
    """Count a refusal raised while validating the body: ``-1`` sign, ``-8`` malformed.

    The one place a validation :class:`ClickError` is counted. ``-3`` (a signed call for the
    other endpoint) is not a hostile or broken caller, so it counts nothing.
    """
    if exc.code == _SIGN_CHECK_FAILED:
        record_kassa_rejection(provider="click", reason="signature")
    elif exc.code == _BAD_REQUEST:
        record_kassa_rejection(provider="click", reason="malformed")


def _unreadable_body() -> service.ClickResponse:
    """``-8`` for a body that is not Click's form (counted as malformed)."""
    record_kassa_rejection(provider="click", reason="malformed")
    return bad_request().to_response()


def _req_str(form: Form, key: str) -> str:
    """A required, non-empty form field as the raw string Click sent; else ``-8``."""
    value = form.get(key)
    if not value:
        raise bad_request()
    return value


def _req_int(form: Form, key: str) -> int:
    """A required form field parsed as an integer; else ``-8``."""
    try:
        return int(_req_str(form, key))
    except ValueError:
        raise bad_request() from None


def _echo(form: Form) -> dict[str, str]:
    """``click_trans_id`` / ``merchant_trans_id`` as sent, whichever the request carried."""
    return {key: form[key] for key in ("click_trans_id", "merchant_trans_id") if form.get(key)}


def _log_outcome(method: str, form: Form | None, body: service.ClickResponse) -> None:
    """One line per callback: method, outcome code, number and amount (never the sign)."""
    fields = form or {}
    log.info(
        "click.callback",
        method=method,
        error=body["error"],
        number=fields.get("merchant_trans_id", "")[:_LOG_NUMBER_MAX] or None,
        amount=fields.get("amount", "")[:_LOG_NUMBER_MAX] or None,
    )


async def _rollback_after_internal_error(db: AsyncSession, *, method: str) -> None:
    """Best-effort rollback after an unexpected exception, logging either way."""
    try:
        await db.rollback()
    except Exception:
        log.exception("click.webhook.rollback_failed", method=method)
    log.exception("click.webhook.internal_error", method=method)


async def _run(
    db: AsyncSession,
    *,
    method: str,
    form: Form,
    handler: Callable[[], Awaitable[service.ClickResponse]],
) -> service.ClickResponse:
    """Run a handler and commit; render a :class:`ClickError` or any failure as a body.

    A ``persist`` error commits what the handler wrote (a cancelled transaction) before
    refusing; any other error rolls back. The commit is inside the guard on purpose.
    """
    try:
        try:
            body = await handler()
        except ClickError as exc:
            await (db.commit() if exc.persist else db.rollback())
            return exc.to_response(**_echo(form))
        await db.commit()
    except Exception:  # noqa: BLE001 -- must render -7 at HTTP 200, never a 500
        await _rollback_after_internal_error(db, method=method)
        return failed_to_update().to_response(**_echo(form))
    return body


async def _read_form(request: Request) -> Form | None:
    """The urlencoded body as raw strings, or ``None`` (answered ``-8``) when it is not one.

    Not ``application/x-www-form-urlencoded``, over :data:`_MAX_BODY_BYTES`, not UTF-8 or
    over :data:`_MAX_FIELDS` fields — none of these is a Click call.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        return None
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > _MAX_BODY_BYTES:
            return None
    try:
        pairs = parse_qsl(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=_MAX_FIELDS)
    except ValueError:  # UnicodeDecodeError included; too many fields
        return None
    return dict(pairs)


def _verify(expected_for: Callable[[str], str], *, service_id: int, sign_string: str) -> None:
    """``-1`` unless ``service_id`` is ours and the sign string matches."""
    secret = signature.secret_for_service(service_id)
    if secret is None or not signature.verify(expected_for(secret), sign_string):
        raise sign_check_failed()


def _check_prepare(form: Form) -> tuple[int, int, int, int]:
    """Validate a prepare body: fields (``-8``), signature (``-1``), action (``-3``).

    Returns:
        ``(click_trans_id, service_id, click_paydoc_id, error)`` parsed.
    """
    raw = {
        key: _req_str(form, key)
        for key in (
            "click_trans_id",
            "service_id",
            "click_paydoc_id",
            "merchant_trans_id",
            "amount",
            "action",
            "error",
            "error_note",
            "sign_time",
            "sign_string",
        )
    }
    ids = (
        _req_int(form, "click_trans_id"),
        _req_int(form, "service_id"),
        _req_int(form, "click_paydoc_id"),
        _req_int(form, "error"),
    )
    action = _req_int(form, "action")
    _verify(
        lambda secret: signature.prepare_sign(
            click_trans_id=raw["click_trans_id"],
            service_id=raw["service_id"],
            secret=secret,
            merchant_trans_id=raw["merchant_trans_id"],
            amount=raw["amount"],
            action=raw["action"],
            sign_time=raw["sign_time"],
        ),
        service_id=ids[1],
        sign_string=raw["sign_string"],
    )
    if action != 0:
        raise action_not_found()
    return ids


def _check_complete(form: Form) -> tuple[int, int, int, int]:
    """Validate a complete body: fields (``-8``), signature (``-1``), action (``-3``).

    Returns:
        ``(click_trans_id, service_id, merchant_prepare_id, error)`` parsed.
    """
    raw = {
        key: _req_str(form, key)
        for key in (
            "click_trans_id",
            "service_id",
            "click_paydoc_id",
            "merchant_trans_id",
            "merchant_prepare_id",
            "amount",
            "action",
            "error",
            "error_note",
            "sign_time",
            "sign_string",
        )
    }
    ids = (
        _req_int(form, "click_trans_id"),
        _req_int(form, "service_id"),
        _req_int(form, "merchant_prepare_id"),
        _req_int(form, "error"),
    )
    action = _req_int(form, "action")
    _verify(
        lambda secret: signature.complete_sign(
            click_trans_id=raw["click_trans_id"],
            service_id=raw["service_id"],
            secret=secret,
            merchant_trans_id=raw["merchant_trans_id"],
            merchant_prepare_id=raw["merchant_prepare_id"],
            amount=raw["amount"],
            action=raw["action"],
            sign_time=raw["sign_time"],
        ),
        service_id=ids[1],
        sign_string=raw["sign_string"],
    )
    if action != 1:
        raise action_not_found()
    return ids


async def _prepare(db: AsyncSession, form: Form) -> service.ClickResponse:
    try:
        click_trans_id, service_id, click_paydoc_id, error = _check_prepare(form)
    except ClickError as exc:
        _count_rejection(exc)
        return exc.to_response(**_echo(form))

    async def handler() -> service.ClickResponse:
        if error < 0:
            await service.cancel(db, click_trans_id=click_trans_id, service_id=service_id)
            return transaction_cancelled().to_response(**_echo(form))
        return await service.prepare(
            db,
            click_trans_id=click_trans_id,
            service_id=service_id,
            click_paydoc_id=click_paydoc_id,
            merchant_trans_id=_req_str(form, "merchant_trans_id"),
            amount=_req_str(form, "amount"),
        )

    return await _run(db, method="prepare", form=form, handler=handler)


async def _complete(db: AsyncSession, form: Form) -> service.ClickResponse:
    try:
        click_trans_id, service_id, merchant_prepare_id, error = _check_complete(form)
    except ClickError as exc:
        _count_rejection(exc)
        return exc.to_response(**_echo(form))

    async def handler() -> service.ClickResponse:
        if error < 0:
            await service.cancel(db, merchant_prepare_id=merchant_prepare_id)
            return transaction_cancelled().to_response(**_echo(form))
        return await service.complete(
            db,
            click_trans_id=click_trans_id,
            service_id=service_id,
            merchant_trans_id=_req_str(form, "merchant_trans_id"),
            merchant_prepare_id=merchant_prepare_id,
            amount=_req_str(form, "amount"),
        )

    return await _run(db, method="complete", form=form, handler=handler)


@router.post("/prepare", summary="Click Shop API: prepare")
async def click_prepare(request: Request, db: DbSession) -> service.ClickResponse:
    """Click's ``/prepare`` (``action=0``): check the top-up, allocate a transaction.

    Authenticated by the MD5 ``sign_string``; always HTTP 200 (see the module docstring).
    Idempotent on Click's ``(click_trans_id, service_id)``, so no ``Idempotency-Key``.
    """
    form = await _read_form(request)
    body = _unreadable_body() if form is None else await _prepare(db, form)
    _log_outcome("prepare", form, body)
    return body


@router.post("/complete", summary="Click Shop API: complete")
async def click_complete(request: Request, db: DbSession) -> service.ClickResponse:
    """Click's ``/complete`` (``action=1``): Click debited the customer; credit the top-up.

    Authenticated by the MD5 ``sign_string``; always HTTP 200. Idempotent on our
    ``merchant_prepare_id`` (a replay is ``-4``), so no ``Idempotency-Key``.
    """
    form = await _read_form(request)
    body = _unreadable_body() if form is None else await _complete(db, form)
    _log_outcome("complete", form, body)
    return body


def _reject_non_post() -> service.ClickResponse:
    """A stray non-POST: ``-8`` at HTTP 200 (Click has no "wrong method" code), never a 405."""
    return _unreadable_body()


for _path in ("/prepare", "/complete"):
    router.add_api_route(
        _path,
        _reject_non_post,
        methods=["GET", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )


__all__ = ["click_complete", "click_prepare", "router"]
