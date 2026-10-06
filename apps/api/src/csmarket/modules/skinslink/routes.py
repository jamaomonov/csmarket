"""``POST /skinslink/webhook`` — Skinslink's status webhook (spec 2026-10-06 §6).

Authenticated by ``sign`` before anything is read from the body; the body is then not
trusted: a purchase webhook queues a check (the worker asks Skinslink), a deposit webhook
(``trade_id``, the future sell side) is answered and ignored. 404 while Skinslink is off.
Machine-to-machine: no ``Idempotency-Key`` (a repeat queues one more idempotent check) and
off the coarse limiter (``bootstrap._exempt_self_authenticating_routes``).
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.errors import ForbiddenError, NotFoundError, ValidationError
from csmarket.core.logging import get_logger
from csmarket.core.request_body import read_capped
from csmarket.modules.skinslink.checks import enqueue_check
from csmarket.modules.skinslink.webhook import verify

router = APIRouter(prefix="/skinslink", tags=["skinslink"])
log = get_logger("csmarket.skinslink.webhook")

DbSession = Annotated[AsyncSession, Depends(db_session)]
#: A webhook body is a handful of short fields.
_MAX_BODY = 4096


class _BadBodyError(ValidationError):
    status_code = 400
    title = "Bad request"


@router.post("/webhook", include_in_schema=False)
async def skinslink_webhook(request: Request, db: DbSession) -> dict[str, bool]:
    """Skinslink's purchase / deposit status webhook (signed; the status is not read)."""
    settings = get_settings()
    if not settings.skinslink_active:
        raise NotFoundError("not found")
    raw = await read_capped(request, _MAX_BODY)
    try:
        body = json.loads(raw) if raw is not None else None
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise _BadBodyError("not a webhook body", code="bad_body")
    pid = verify(body, secret=settings.skinslink_secret)
    if pid is None:
        raise ForbiddenError("bad signature", code="bad_signature")
    kind = "purchase" if "purchase_id" in body else "deposit"
    if kind == "purchase":
        await enqueue_check(db, pid)
        await db.commit()
    log.info("skinslink.webhook", kind=kind)
    return {"ok": True}


__all__ = ["router", "skinslink_webhook"]
