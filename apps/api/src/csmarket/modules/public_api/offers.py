"""Offers for the public API: Skinslink and LIS-SKINS only, priced by the key's tariff.

The offer id a partner sees is opaque: ``item_id|offer_id`` sealed under the
``public_offer`` purpose, so it hides the source and cannot be moved to another item.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime

from nacl.exceptions import CryptoError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.core.crypto import NONCE_SIZE, decrypt, encrypt
from csmarket.modules.lisskins.api import offers_for as lisskins_offers
from csmarket.modules.skins.api import PricingRules, SkinItem, load_rules, quote
from csmarket.modules.skins.offers import TIE_ORDER, Offer, merge_offers
from csmarket.modules.skinslink.api import offers_for as skinslink_offers

_PURPOSE = "public_offer"


def seal_offer_id(item_id: str, offer_id: str) -> str:
    """Seal ``item_id|offer_id`` into an opaque url-safe token (no padding)."""
    ciphertext, nonce = encrypt(f"{item_id}|{offer_id}", purpose=_PURPOSE)
    return base64.urlsafe_b64encode(nonce + ciphertext).rstrip(b"=").decode("ascii")


def open_offer_id(token: str, item_id: str) -> str | None:
    """The internal offer id behind ``token``, or ``None`` if it is bad or for another item."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        if len(raw) <= NONCE_SIZE:
            return None
        plain = decrypt(raw[NONCE_SIZE:], raw[:NONCE_SIZE], purpose=_PURPOSE)
    except (ValueError, binascii.Error, CryptoError):
        return None
    owner, sep, offer_id = plain.partition("|")
    return offer_id if sep and owner == item_id else None


@dataclass(frozen=True)
class PricedOffer:
    """An offer with the partner's price and the storefront (retail) price, in units."""

    offer: Offer
    price_units: int
    retail_units: int
    #: The sealed id the partner sees (bound to the offer's item).
    public_id: str


def price_units_for(
    units: int, *, profile: str, item: SkinItem, rules: PricingRules, stock: int
) -> tuple[int, int]:
    """``(price_units, retail_units)``: retail is the storefront quote; ``cost`` bills ``units``."""
    retail = int(
        quote(
            units,
            rules=rules,
            category=item.category,
            weapon=item.weapon,
            count_auto=stock,
            item_pp=item.margin_override_pp,
            fixed_price_usd=item.fixed_price_usd,
            steam_price_units=item.steam_price_units,
        ).price_usd
        * 1000
    )
    return (units if profile == "cost" else retail), retail


async def api_offers(
    db: AsyncSession, item: SkinItem, *, profile: str, settings: Settings, now: datetime
) -> list[PricedOffer]:
    """Skinslink + LIS-SKINS offers of ``item``, cheapest first, priced for ``profile``."""
    rules = await load_rules(db)
    # ``merge_offers`` shows a Steam asset both sources list once, as the storefront does.
    offers = merge_offers(
        await skinslink_offers(db, item.id, settings=settings, now=now),
        await lisskins_offers(db, item.id, settings=settings, now=now),
    )
    stock = item.stock_count
    priced: list[PricedOffer] = []
    for offer in offers:
        price, retail = price_units_for(
            offer.price_units, profile=profile, item=item, rules=rules, stock=stock
        )
        priced.append(PricedOffer(offer, price, retail, seal_offer_id(item.id, offer.offer_id)))
    priced.sort(key=lambda p: (p.price_units, TIE_ORDER[p.offer.source], p.offer.offer_id))
    return priced
