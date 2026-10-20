"""``POST /api/v1/webhooks/telegram/p2p`` — HUMO notifications through the relay
(spec 2026-10-19-p2p-topup).

Authenticity first: the relay sends csmarket's own secret in
``X-Telegram-Bot-Api-Secret-Token``; it is compared before a byte of the body is read, and an
unset secret refuses everything. Idempotency-Key does not apply: the journal's
``(business_connection_id, message_id)`` unique key makes a retry a no-op.
"""

from __future__ import annotations

import hmac
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.metrics import record_p2p_notification
from csmarket.core.request_body import read_capped
from csmarket.modules.p2p.intake import ingest_update

router = APIRouter(prefix="/webhooks/telegram", tags=["webhooks"])
MAX_BODY_BYTES = 64 * 1024


@router.post("/p2p", status_code=status.HTTP_200_OK, summary="HUMO notifications (P2P)")
async def p2p_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session, scope="function")],
    secret: Annotated[str, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = "",
) -> dict[str, Any]:
    """Verify the secret header, journal the update, settle a matching request."""
    expected = get_settings().p2p_webhook_secret
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    raw = await read_capped(request, MAX_BODY_BYTES)
    if raw is None:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    try:
        update = json.loads(raw)
    except ValueError:
        return {"ok": True}  # Telegram's own body; a retry would be the same bytes.
    if not isinstance(update, dict):
        return {"ok": True}
    result = await ingest_update(db, update, received_at=now())
    await db.commit()
    record_p2p_notification(result.status, result.alerts)
    return {"ok": True}


__all__ = ["router"]
