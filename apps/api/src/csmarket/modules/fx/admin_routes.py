"""``POST /api/v1/admin/fx/rate`` — «Курс вручную»: the admin sets the CBU rate by hand when
neither cbu.uz nor the fallback answers (runbook ``fx-rate.md``). Recorded as
``source='manual'``; the fallback never replaces it while it is fresh. Keyed, audited
``fx.rate.manual``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import record, remember, replayed, require_admin, required_key
from csmarket.modules.fx.cbu import PLAUSIBLE
from csmarket.modules.fx.service import cache_snapshot, record_snapshot
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/fx", tags=["admin"], dependencies=[Depends(require_admin)])

MANUAL_SOURCE = "manual"


class ManualRateIn(BaseModel):
    """Soʻm per dollar, as cbu.uz shows it today."""

    usd_uzs: Annotated[
        Decimal, Field(ge=PLAUSIBLE[0], le=PLAUSIBLE[1], max_digits=10, decimal_places=4)
    ]


class ManualRateOut(BaseModel):
    id: str
    usd_uzs: str
    source: str


@router.post("/rate", response_model=ManualRateOut, status_code=201, summary="Set the rate by hand")
async def post_rate(
    body: ManualRateIn,
    user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(db_session, scope="function")],
    key: Annotated[str, Depends(required_key)],
) -> ManualRateOut:
    """A new snapshot at ``usd_uzs``; soʻm prices use it at once."""
    asked = body.model_dump(mode="json")
    scope = "admin.fx.rate"
    if (hit := await replayed(db, scope=scope, key=key, request=asked)) is not None:
        return ManualRateOut.model_validate(hit)
    row = await record_snapshot(db, rate=body.usd_uzs, source=MANUAL_SOURCE)
    await record(
        db,
        actor_id=user.id,
        action="fx.rate.manual",
        target_type="fx_snapshot",
        target_id=row.id,
        payload={"usd_uzs": str(body.usd_uzs)},
    )
    out = ManualRateOut(
        id=row.id, usd_uzs=format(row.usd_uzs.normalize(), "f"), source=MANUAL_SOURCE
    )
    await remember(db, scope=scope, key=key, request=asked, response=out.model_dump(mode="json"))
    await db.commit()
    await cache_snapshot(get_redis(), row)
    return out
