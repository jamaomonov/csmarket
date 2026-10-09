"""``POST /api/v1/public/tradelink/check`` -- the site's advisory trade-link check for API keys."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.errors import ValidationError
from csmarket.core.redis import get_redis
from csmarket.modules.public_api.auth import ApiCaller, api_caller
from csmarket.modules.public_api.limits import enforce
from csmarket.modules.public_api.metering import MeteredRoute
from csmarket.modules.public_api.schemas import TradeLinkCheckIn, TradeLinkCheckOut
from csmarket.modules.users.api import (
    HoldChecker,
    TradelinkChecker,
    check_trade_link,
    parse_tradelink,
    tradelink_checkers,
)

router = APIRouter(prefix="/public", tags=["public-api"], route_class=MeteredRoute)

#: Internal reason -> the public wire value.
PUBLIC_REASONS: dict[str, str] = {
    "invalid": "invalid_link",
    "private": "private_inventory",
    "trade_ban": "trade_ban",
    "hold": "hold",
    "not_found": "not_found",
}
_AUTH_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "`unauthorized`"},
    403: {"description": "`account_suspended`, `ip_not_allowed`"},
    429: {"description": "`rate_limited`, with `Retry-After`"},
}


@router.post(
    "/tradelink/check",
    response_model=TradeLinkCheckOut,
    summary="Check a trade link before buying",
    responses=_AUTH_ERRORS,
)
async def check_trade_link_route(
    body: TradeLinkCheckIn,
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
    checkers: Annotated[tuple[TradelinkChecker, HoldChecker], Depends(tradelink_checkers)],
) -> TradeLinkCheckOut:
    """Whether a Steam trade can be sent to ``trade_link`` now (advisory).

    No ``Idempotency-Key``: it writes nothing and a repeat is the intended use (the verdict is
    cached 10 minutes). ``POST`` keeps the link's token out of URLs and access logs.
    ``unavailable`` means the check could not run: do not block a purchase on it.
    """
    await enforce(caller, "check")
    try:
        link = parse_tradelink(body.trade_link)
    except ValidationError:
        return TradeLinkCheckOut(verdict="bad", reason="invalid_link")
    await db.commit()  # no connection held across the upstream calls (AGENTS §11)
    waxpeer, hold = checkers
    result = await check_trade_link(link, waxpeer=waxpeer, hold=hold, redis=get_redis())
    if result.verdict is None or result.verdict == "warn":
        return TradeLinkCheckOut(verdict="unavailable", reason=None)
    reason = None if result.reason is None else PUBLIC_REASONS[result.reason]
    return TradeLinkCheckOut.model_validate({"verdict": result.verdict, "reason": reason})
