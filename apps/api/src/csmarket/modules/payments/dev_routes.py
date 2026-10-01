"""Dev-only payment routes (ruling R11): complete a ``mock`` top-up without a kassa.

Every route here answers 404 unless ``settings.dev_login_active`` (never in prod), and none
is in the OpenAPI schema.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session, dev_gate
from csmarket.core.errors import NotFoundError
from csmarket.modules.auth.api import current_user
from csmarket.modules.payments.schemas import TopupOut
from csmarket.modules.payments.topups import dev_pay, owned_topup, topup_view
from csmarket.modules.users.models import User

router = APIRouter(prefix="/dev", tags=["dev"], dependencies=[Depends(dev_gate)])


@router.post("/topups/{number}/pay", response_model=TopupOut, include_in_schema=False)
async def dev_pay_topup(
    number: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TopupOut:
    """Settle the owner's top-up through ``mock`` (the real ``settle`` hook).

    Keyless on purpose: dev-only, and a repeat is a no-op — a paid top-up is returned as
    is and the ledger credits a top-up once.
    """
    topup = await owned_topup(db, user_id=user.id, number=number)
    if topup is None:
        raise NotFoundError("top-up not found")
    await dev_pay(db, number=number)
    return TopupOut.of(await topup_view(db, topup, locale="ru"))
