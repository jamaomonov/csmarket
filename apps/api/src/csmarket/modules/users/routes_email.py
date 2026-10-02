"""Email confirmation routes (M4b ruling R7).

- ``POST /api/v1/me/email/verification`` — send the confirmation letter again (signed in).
- ``POST /api/v1/email/confirm`` — confirm by the link's token (anonymous).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from csmarket.modules.auth.api import current_user, guard_ip
from csmarket.modules.users.email_flow import confirm_email, send_verification
from csmarket.modules.users.models import User
from csmarket.modules.users.schemas import EmailConfirmIn, EmailConfirmOut, VerificationSentOut

me_router = APIRouter(prefix="/me/email", tags=["me"])
router = APIRouter(prefix="/email", tags=["email"])


@me_router.post(
    "/verification",
    response_model=VerificationSentOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send the email confirmation letter again",
)
async def resend_verification(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> VerificationSentOut:
    """Queue a new confirmation letter for the current, unconfirmed email.

    409 ``email_missing`` / ``email_already_verified``; 429 ``email_verify_cooldown`` within
    60 s of the last letter; 429 past the ``email-verify`` bucket. A repeated
    ``Idempotency-Key`` replays the first answer and sends nothing.
    """
    await guard_ip(request, bucket="email-verify", subject=user.id)
    key = normalize_idempotency_key(idempotency_key)
    scope = f"users.email_verification:{user.id}"
    if key is not None and await load_replay(db, scope=scope, idempotency_key=key) is not None:
        return VerificationSentOut(sent=True)
    await send_verification(db, user, resend=True)
    out = VerificationSentOut(sent=True)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@router.post("/confirm", response_model=EmailConfirmOut, summary="Confirm an email by its link")
async def confirm(
    request: Request,
    body: EmailConfirmIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> EmailConfirmOut:
    """Confirm the address a link's token names; anonymous, so a link opened on another
    device works.

    Keyless: the token is single-purpose and the write is idempotent — confirming twice
    answers 200 twice and stamps once. 422 ``email_token_invalid`` / ``email_token_expired``;
    409 ``email_token_stale`` when the account's email is no longer the token's.
    """
    await guard_ip(request, bucket="email-verify")
    await confirm_email(db, body.token)
    return EmailConfirmOut(email_verified=True)
