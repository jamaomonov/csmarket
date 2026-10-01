"""Dev-only Waxpeer route: set the dev fake's balance (the ``WaxpeerBalanceLow`` path).

404 unless ``settings.dev_login_active`` (never in prod) and the fake is on; not in the
OpenAPI schema.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from csmarket.api.v1.deps import dev_gate
from csmarket.modules.auth.api import current_user
from csmarket.modules.skins.waxpeer_fake import FakeTradeClient, fake_client
from csmarket.modules.users.api import User

router = APIRouter(prefix="/dev/waxpeer", tags=["dev"], dependencies=[Depends(dev_gate)])


class DevBalanceIn(BaseModel):
    """The fake's new balance in Waxpeer units (1000 = $1)."""

    model_config = ConfigDict(extra="forbid")

    units: int = Field(ge=0)


@router.post("/balance", response_model=DevBalanceIn, include_in_schema=False)
async def dev_set_balance(
    body: DevBalanceIn,
    _user: Annotated[User, Depends(current_user)],
    fake: Annotated[FakeTradeClient, Depends(fake_client)],
) -> DevBalanceIn:
    """Set the fake Waxpeer balance; any signed-in account (dev only).

    Keyless on purpose: dev-only, and it sets an absolute value, so a repeat changes nothing.
    """
    await fake.set_balance(body.units)
    return DevBalanceIn(units=await fake.balance_units())


__all__ = ["router"]
