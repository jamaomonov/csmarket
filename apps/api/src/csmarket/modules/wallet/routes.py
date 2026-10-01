"""``/api/v1/wallet`` — the signed-in customer's balance and its history.

Top-ups (``/wallet/topups``) are mounted from ``payments.routes``: ``wallet`` never imports
``payments``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.auth.api import current_user
from csmarket.modules.users.models import User
from csmarket.modules.wallet.entries import DEFAULT_LIMIT, MAX_LIMIT, entries_for_user
from csmarket.modules.wallet.schemas import BalanceOut, EntriesOut
from csmarket.modules.wallet.service import user_balance

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("", response_model=BalanceOut, summary="My balance")
async def get_balance(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> BalanceOut:
    """Spendable soʻm; ``"0"`` before the first top-up."""
    return BalanceOut.of(await user_balance(db, user.id))


@router.get("/entries", response_model=EntriesOut, summary="My balance history")
async def get_entries(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> EntriesOut:
    """Newest first; pass ``next_cursor`` back as ``cursor`` for the next page."""
    return EntriesOut.of(await entries_for_user(db, user.id, cursor=cursor, limit=limit))
