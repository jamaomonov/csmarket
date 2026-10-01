"""Customer payment routes: the provider list and ``/wallet/topups``.

The top-up routes live here under the ``/wallet`` prefix, not in ``wallet/routes.py``:
``payments`` builds on ``wallet`` and ``wallet`` never imports ``payments``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.errors import NotFoundError, ValidationError
from csmarket.core.idempotency import IDEMPOTENCY_HEADER, normalize_idempotency_key
from csmarket.modules.auth.api import current_user, guard_ip
from csmarket.modules.payments.gateways import available_providers
from csmarket.modules.payments.schemas import (
    Locale,
    ProviderOut,
    ProvidersOut,
    TopupIn,
    TopupOut,
)
from csmarket.modules.payments.topups import (
    TopupView,
    awaiting_kassa,
    create_topup,
    owned_topup,
    topup_view,
)
from csmarket.modules.users.models import User

router = APIRouter(prefix="/payments", tags=["payments"])
wallet_router = APIRouter(prefix="/wallet", tags=["wallet"])

#: ``wallet_topups.idempotency_key`` is ``varchar(160)``.
_MAX_KEY_LENGTH = 160


def _required_key(value: str | None) -> str:
    """The ``Idempotency-Key`` a top-up must carry: 16 to 160 characters."""
    key = normalize_idempotency_key(value)
    if key is None or len(key) > _MAX_KEY_LENGTH:
        raise ValidationError(
            f"{IDEMPOTENCY_HEADER} header of 16 to {_MAX_KEY_LENGTH} characters is required",
            header=IDEMPOTENCY_HEADER,
        )
    return key


@router.get("/providers", response_model=ProvidersOut, summary="Kassas available now")
async def list_providers() -> ProvidersOut:
    """Anonymous: the storefront shows these tiles on the balance page."""
    return ProvidersOut(providers=[ProviderOut(slug=slug) for slug in available_providers()])


@wallet_router.post(
    "/topups", response_model=TopupOut, status_code=201, summary="Open a balance top-up"
)
async def post_topup(
    body: TopupIn,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> TopupOut:
    """Open a top-up in the chosen kassa; the response says where to pay.

    ``Idempotency-Key`` is required. The same key with the same amount and kassa returns
    the same top-up (201 again); with another amount or kassa it is a 409
    ``idempotency_mismatch``.
    """
    key = _required_key(idempotency_key)
    await guard_ip(request, bucket="topup-create", subject=user.id)
    topup, payment, url = await create_topup(
        db,
        user_id=user.id,
        amount_uzs=Decimal(body.amount_uzs),
        provider=body.provider,
        idempotency_key=key,
        locale=body.locale,
    )
    view = TopupView(
        topup=topup,
        provider=payment.provider,
        intent_url=url,
        awaiting_kassa=await awaiting_kassa(db, topup),
    )
    return TopupOut.of(view)


@wallet_router.get("/topups/{number}", response_model=TopupOut, summary="One of my top-ups")
async def get_topup(
    number: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Locale = "ru",
) -> TopupOut:
    """The owner's top-up; anyone else's (or an unknown number) is a 404, never a 403."""
    topup = await owned_topup(db, user_id=user.id, number=number)
    if topup is None:
        raise NotFoundError("top-up not found")
    return TopupOut.of(await topup_view(db, topup, locale=locale))
