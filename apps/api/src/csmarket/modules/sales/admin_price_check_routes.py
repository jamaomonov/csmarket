"""``POST /api/v1/admin/sales/price-check`` — «Проверить цену выкупа» (:mod:`.admin_price_check`).

Admin only. Keyless: it writes nothing (no trade record at Skinslink, nothing of ours), so a
repeat is only another look. Mounted before :mod:`.admin_routes` so ``price-check`` never reads
as a sale number.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.errors import ValidationError
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import require_admin
from csmarket.modules.sales.admin_price_check import (
    MAX_NAMES,
    PriceCheck,
    by_names,
    by_trade_link,
    clean_names,
)
from csmarket.modules.sales.clients import inventory_client
from csmarket.modules.sales.rules import CardType
from csmarket.modules.skinslink.api import DepositClient
from csmarket.modules.users.api import parse_tradelink

router = APIRouter(prefix="/admin/sales", tags=["admin"], dependencies=[Depends(require_admin)])


class PriceCheckIn(BaseModel):
    """Exactly one: market names (one per line in the admin) or a Steam trade link."""

    names: list[Annotated[str, Field(max_length=200)]] | None = Field(
        default=None, min_length=1, max_length=MAX_NAMES
    )
    trade_link: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _one(self) -> PriceCheckIn:
        if (self.names is None) == (self.trade_link is None):
            raise ValueError("give names or a trade link")
        return self


class CheckedItemOut(BaseModel):
    name: str
    image_url: str | None
    skinslink_usd: str
    #: Skinslink's raw price before its multipliers (names only).
    original_usd: str | None
    #: What we would pay for it, soʻm, before the balance bonus or a card fee.
    price_uzs: str
    margin_usd: str


class TotalsOut(BaseModel):
    skinslink_usd: str
    items_uzs: str
    balance_uzs: str
    card_uzs: dict[CardType, str]
    margin_usd: str


class PriceCheckOut(BaseModel):
    items: list[CheckedItemOut]
    #: Names Skinslink does not buy now.
    missing: list[str]
    totals: TotalsOut
    #: The sale rate used (CBU less the cut), soʻm per dollar.
    rate: str

    @classmethod
    def of(cls, c: PriceCheck) -> PriceCheckOut:
        """Strings for the money."""
        return cls(
            items=[
                CheckedItemOut(
                    name=i.name,
                    image_url=i.image_url,
                    skinslink_usd=_plain(i.skinslink_usd),
                    original_usd=None if i.original_usd is None else _plain(i.original_usd),
                    price_uzs=_plain(i.price_uzs),
                    margin_usd=_plain(i.margin_usd),
                )
                for i in c.items
            ],
            missing=c.missing,
            totals=TotalsOut(
                skinslink_usd=_plain(c.totals.skinslink_usd),
                items_uzs=_plain(c.totals.items_uzs),
                balance_uzs=_plain(c.totals.balance_uzs),
                card_uzs={t: _plain(v) for t, v in c.totals.card_uzs.items()},
                margin_usd=_plain(c.totals.margin_usd),
            ),
            rate=_plain(c.rate),
        )


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


@router.post("/price-check", response_model=PriceCheckOut, summary="Skinslink buy-back prices")
async def price_check(
    body: PriceCheckIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    client: Annotated[DepositClient, Depends(inventory_client)],
) -> PriceCheckOut:
    """What Skinslink pays and what we would pay, by names or a trade link's inventory.

    Keyless: it writes nothing anywhere.
    """
    settings = get_settings()
    redis = get_redis()
    if body.trade_link is not None:
        link = parse_tradelink(body.trade_link)
        return PriceCheckOut.of(await by_trade_link(db, redis, settings, client, link))
    names = clean_names(body.names or [])
    if not names:
        raise ValidationError("give at least one name", code="names_empty")
    return PriceCheckOut.of(await by_names(db, redis, settings, client, names))
