"""``/api/v1/wallet`` — the signed-in customer's balance and its history.

Top-ups (``/wallet/topups``) are mounted from ``payments.routes``: ``wallet`` never imports
``payments``.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.errors import ForbiddenError, UpstreamUnavailableError
from csmarket.core.idempotency import require_idempotency_key
from csmarket.core.redis import get_redis
from csmarket.modules.auth.api import current_user
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.users.models import User
from csmarket.modules.wallet.convert import conversion_booked, convert_to_usd
from csmarket.modules.wallet.entries import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    EntryType,
    entries_for_user,
)
from csmarket.modules.wallet.schemas import BalanceOut, ConvertIn, ConvertOut, EntriesOut
from csmarket.modules.wallet.service import user_balance, user_usd_balance

router = APIRouter(prefix="/wallet", tags=["wallet"])


class RateUnavailableError(UpstreamUnavailableError):
    """No fresh soʻm rate: nothing can be converted right now."""

    status_code = 503
    type_uri = "https://csmarket.uz/errors/rate-unavailable"
    title = "Rate unavailable"


@router.get("", response_model=BalanceOut, summary="My balance")
async def get_balance(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> BalanceOut:
    """Spendable soʻm; ``"0"`` before the first top-up.

    ``usd`` carries the dollar wallet and today's conversion rate once an admin switched it on
    for the account; ``null`` otherwise.
    """
    uzs = await user_balance(db, user.id)
    if not user.usd_wallet_enabled:
        return BalanceOut.of(uzs)
    rate = await current_usd_uzs(db, get_redis(), max_age_days=get_settings().fx_max_age_days)
    return BalanceOut.of(
        uzs, usd=await user_usd_balance(db, user.id), rate=None if rate is None else rate.rate
    )


@router.get("/entries", response_model=EntriesOut, summary="My balance history")
async def get_entries(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    *,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    entry_type: Annotated[EntryType | None, Query(alias="type")] = None,
    currency: Literal["uzs", "usd"] = "uzs",
) -> EntriesOut:
    """Newest first; pass ``next_cursor`` back as ``cursor`` for the next page.

    ``type=topup`` keeps top-ups and their reversals; ``type=withdrawal`` is empty until
    payouts exist. ``currency=usd`` lists the dollar wallet's lines (``amount_usd``).
    """
    wallet: Literal["UZS", "USD"] = "USD" if currency == "usd" else "UZS"
    page = await entries_for_user(
        db, user.id, cursor=cursor, limit=limit, entry_type=entry_type, currency=wallet
    )
    return EntriesOut.of(page, wallet)


@router.post(
    "/convert", response_model=ConvertOut, status_code=201, summary="Convert soʻm into dollars"
)
async def convert(
    body: ConvertIn,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ConvertOut:
    """Soʻm → the dollar wallet at the site rate (CBU plus the uplift).

    Needs the dollar wallet switched on. A replayed key with the same amount answers 200 with
    the same conversion; the same key with another amount is 409.
    """
    key = require_idempotency_key(idempotency_key)
    if not user.usd_wallet_enabled:
        raise ForbiddenError("the USD wallet is not switched on", code="usd_wallet_disabled")
    rate = await current_usd_uzs(db, get_redis(), max_age_days=get_settings().fx_max_age_days)
    if rate is None:
        raise RateUnavailableError("no soʻm rate", code="rate_unavailable")
    # Namespaced by user so two accounts' keys never collide; hashed to a fixed length so a
    # long client key fits the ledger's String(160) column.
    ledger_key = hashlib.sha256(f"{user.id}:{key}".encode()).hexdigest()
    replay = await conversion_booked(db, f"fx_convert:{ledger_key}")
    conv = await convert_to_usd(
        db,
        user_id=user.id,
        amount_uzs=Decimal(body.amount_uzs),
        rate=rate.rate,
        snapshot_id=rate.snapshot_id,
        idempotency_key=ledger_key,
    )
    await db.commit()
    if replay:
        response.status_code = 200
    return ConvertOut.of(
        conv, uzs=await user_balance(db, user.id), usd=await user_usd_balance(db, user.id)
    )
