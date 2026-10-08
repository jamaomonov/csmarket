"""Rows for the sales tests: cards, sales with their items, payout requests.

Card numbers here are made up (Luhn-valid, the right prefixes) and never belong to anyone.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from csmarket.core.crypto import encrypt
from csmarket.core.ids import new_id
from csmarket.core.numbers import allocate, sale_number
from csmarket.modules.sales.models import (
    CARD_PURPOSE,
    PayoutCard,
    PayoutRequest,
    Sale,
    SaleItem,
    SaleSettingsRow,
)
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS, SaleSettings
from csmarket.modules.users.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

#: The CBU rate the sales tests price with (no uplift, no cut).
RATE = Decimal("12650.5")
HUMO = "9860123456789015"
UZCARD = "8600123456789012"
VISA = "4000000000000002"
#: ``(asset_id, name, Skinslink USD, our soʻm)`` — the spec's two-item example at RATE with the
#: default brackets: 12.45 $ → 149 600, 0.50 $ → 5 600.
ITEMS: tuple[tuple[str, str, Decimal, Decimal], ...] = (
    ("100", "AK-47 | Redline (Field-Tested)", Decimal("12.45"), Decimal(149_600)),
    ("101", "P250 | Sand Dune (Field-Tested)", Decimal("0.5"), Decimal(5_600)),
)


async def make_card(
    db: AsyncSession, user: User, *, card_type: str = "humo", number: str = HUMO
) -> PayoutCard:
    """A committed, encrypted card of ``user``."""
    enc, nonce = encrypt(number, purpose=CARD_PURPOSE)
    card = PayoutCard(
        id=new_id(),
        user_id=user.id,
        type=card_type,
        number_enc=enc,
        number_nonce=nonce,
        last4=number[-4:],
    )
    db.add(card)
    await db.commit()
    return card


async def make_sale(
    db: AsyncSession,
    *,
    user: User | None = None,
    status: str = "offered",
    payout_to: str = "balance",
    card: PayoutCard | None = None,
    items: tuple[tuple[str, str, Decimal, Decimal], ...] = ITEMS,
    payout_uzs: Decimal | None = None,
    **over: object,
) -> Sale:
    """A committed sale with ``items`` (a new user's unless ``user``; ``over`` replaces any
    column). A card sale gets a new card unless ``card`` or ``payout_card_id`` is given."""
    owner = user or await make_user(db)
    if payout_to == "card" and card is None and "payout_card_id" not in over:
        card = await make_card(db, owner)
    items_uzs = sum((i[3] for i in items), Decimal(0))
    values: dict[str, object] = {
        "id": new_id(),
        "number": await allocate(db, Sale.number, sale_number),
        "user_id": owner.id,
        "status": status,
        "payout_to": payout_to,
        "payout_card_id": card.id if card is not None else None,
        "quoted_usd": sum((i[2] for i in items), Decimal(0)),
        "items_uzs": items_uzs,
        "payout_uzs": payout_uzs if payout_uzs is not None else items_uzs,
        "rate": RATE,
        "margin_usd": Decimal("0.6735"),
        "trade_offer_id": "6912345678" if status != "creating" else None,
        "idempotency_key": f"test-{uuid4()}",
    }
    values.update(over)
    sale = Sale(**values)
    db.add(sale)
    db.add_all(
        SaleItem(sale_id=sale.id, asset_id=a, name=n, price_usd=usd, price_uzs=uzs)
        for a, n, usd, uzs in items
    )
    await db.commit()
    return sale


async def make_request(
    db: AsyncSession, sale: Sale, *, status: str = "to_pay", **over: object
) -> PayoutRequest:
    """A committed payout request of the card sale ``sale``."""
    assert sale.payout_card_id is not None, "a card sale"
    values: dict[str, object] = {
        "id": new_id(),
        "sale_id": sale.id,
        "user_id": sale.user_id,
        "card_id": sale.payout_card_id,
        "amount_uzs": sale.payout_uzs,
        "fee_uzs": sale.items_uzs - sale.payout_uzs,
        "status": status,
    }
    values.update(over)
    request = PayoutRequest(**values)
    db.add(request)
    await db.commit()
    return request


async def enable_sales(db: AsyncSession, **over: object) -> SaleSettings:
    """Row 1 = the default document switched on (``over`` replaces any field); commit."""
    doc = DEFAULT_SALE_SETTINGS.model_copy(update={"enabled": True, **over})
    existing = await db.get(SaleSettingsRow, 1)
    document = doc.model_dump(mode="json")
    if existing is None:
        db.add(SaleSettingsRow(id=1, settings=document))
    else:
        existing.settings = document
    await db.commit()
    return doc
