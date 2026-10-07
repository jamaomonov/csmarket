"""LIS-SKINS values that do not fit our columns never reach a write: one oversized string
must not halt the snapshot or an order's status."""

from __future__ import annotations

from decimal import Decimal

from csmarket.modules.lisskins.api import Purchase, PurchasedSkin
from csmarket.modules.lisskins.export import INSTANT, lot_of
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders.lisskins_status import mirror_report


def _raw(**over: object) -> dict[str, object]:
    return {
        "id": 5,
        "name": "AK-47 | Redline (Field-Tested)",
        "price": 12.34,
        "delivery_type": INSTANT,
        "unlock_at": None,
        "item_asset_id": "41234567890",
        "item_paint_seed": 661,
        **over,
    }


def test_an_oversized_asset_id_or_seed_is_dropped_not_the_lot() -> None:
    lot = lot_of(_raw(item_asset_id="9" * 40, item_paint_seed=2**40))
    assert lot is not None
    assert (lot.asset_id, lot.paint_seed) == (None, None)
    fits = lot_of(_raw())
    assert fits is not None
    assert (fits.asset_id, fits.paint_seed) == ("41234567890", 661)


def test_a_long_status_text_is_cut_to_its_column() -> None:
    p = LisskinsPurchase(order_id="o", custom_id="o", skin_id=5, paid_units=1, buy_pending=False)
    long = "too_many_failed_attempts_for_user_and_more"
    skin = PurchasedSkin(
        id=5,
        status="return_with_a_much_longer_word",
        return_reason=long,
        error=long,
        offer_id="7" * 40,
        offer_expiry_at=None,
        price_usd=Decimal("12.34"),
    )
    mirror_report(p, Purchase(purchase_id=55, custom_id="o", skins=(skin,)))
    assert p.status is not None
    assert len(p.status) <= 16
    assert all(
        v is not None and len(v) <= 32 for v in (p.return_reason, p.error, p.steam_trade_offer_id)
    )
    assert p.error == long[:32]
