"""Trade fields: steam_offer_id and seller_name (spec v1.1 §8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.public_view import _offer_id, _seller_name, public_order
from csmarket.modules.skinslink.models import SkinslinkPurchase


@pytest.fixture
def order() -> Order:
    """A minimal order for testing."""
    return Order(
        id=new_id(),
        number="AB123456",
        user_id=str(uuid4()),
        status="trade_sent",
        skin_item_id=str(uuid4()),
        market_hash_name="AK-47 | Redline",
        phase="",
        slug="ak-47-redline",
        source="waxpeer",
        cost_units=10_000,
        cost_usd=Decimal("10.000"),
        price_usd=Decimal("11.000"),
        price_uzs=Decimal(139_150),
        fx_snapshot_id=str(uuid4()),
        trade_link="https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKE",
        idempotency_key="test-key",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        trade_sent_at=datetime.now(UTC),
    )


def test_offer_id_from_skinslink_purchase() -> None:
    """Skinslink purchase ``offer_id`` is returned."""
    purchase = SkinslinkPurchase(
        order_id="test-order",
        merchant_tx_id="tx123",
        asset_id="123456",
        paid_units=10_000,
        offer_id="7712345678",
    )
    assert _offer_id(None, purchase) == "7712345678"


def test_offer_id_from_lisskins_purchase() -> None:
    """LIS-SKINS purchase ``steam_trade_offer_id`` is returned."""
    purchase = LisskinsPurchase(
        order_id="test-order",
        custom_id="cid123",
        skin_id=12345,
        paid_units=10_000,
        steam_trade_offer_id="7712345679",
    )
    assert _offer_id(None, purchase) == "7712345679"


def test_offer_id_from_waxpeer_trade() -> None:
    """Waxpeer trade ``trade_id`` is returned."""
    trade = SkinTrade(
        order_id="test-order",
        project_id="proj123",
        listing_id=999,
        paid_units=10_000,
        trade_id="7712345680",
    )
    assert _offer_id(trade, None) == "7712345680"


def test_offer_id_empty_string_returns_none() -> None:
    """Empty string offer_id is treated as None."""
    purchase = SkinslinkPurchase(
        order_id="test-order",
        merchant_tx_id="tx123",
        asset_id="123456",
        paid_units=10_000,
        offer_id="",
    )
    assert _offer_id(None, purchase) is None


def test_offer_id_none_returns_none() -> None:
    """None offer_id is returned as None."""
    purchase = SkinslinkPurchase(
        order_id="test-order",
        merchant_tx_id="tx123",
        asset_id="123456",
        paid_units=10_000,
        offer_id=None,
    )
    assert _offer_id(None, purchase) is None


def test_offer_id_none_when_no_purchase_or_trade() -> None:
    """None is returned when no purchase or trade exists."""
    assert _offer_id(None, None) is None


def test_seller_name_from_waxpeer_trade() -> None:
    """Waxpeer trade ``seller`` name is returned."""
    trade = SkinTrade(
        order_id="test-order",
        project_id="proj123",
        listing_id=999,
        paid_units=10_000,
        seller={"name": "bob", "level": 5},
    )
    assert _seller_name(trade) == "bob"


def test_seller_name_empty_string_returns_none() -> None:
    """Empty string seller name is treated as None."""
    trade = SkinTrade(
        order_id="test-order",
        project_id="proj123",
        listing_id=999,
        paid_units=10_000,
        seller={"name": ""},
    )
    assert _seller_name(trade) is None


def test_seller_name_missing_key_returns_none() -> None:
    """Missing 'name' key in seller dict returns None."""
    trade = SkinTrade(
        order_id="test-order",
        project_id="proj123",
        listing_id=999,
        paid_units=10_000,
        seller={"level": 5},
    )
    assert _seller_name(trade) is None


def test_seller_name_none_trade_returns_none() -> None:
    """None trade returns None seller_name."""
    assert _seller_name(None) is None


def test_seller_name_non_string_value_returns_none() -> None:
    """Non-string name value returns None."""
    trade = SkinTrade(
        order_id="test-order",
        project_id="proj123",
        listing_id=999,
        paid_units=10_000,
        seller={"name": 123},  # type: ignore[arg-type]
    )
    assert _seller_name(trade) is None


def test_skinslink_order_has_offer_id_no_seller_name(order: Order) -> None:
    """A Skinslink order returns steam_offer_id but no seller_name."""
    purchase = SkinslinkPurchase(
        order_id=order.id,
        merchant_tx_id="tx123",
        asset_id="123456",
        paid_units=10_000,
        offer_id="7712345678",
    )
    result = public_order(order, None, purchase)
    assert result.trade is not None
    assert result.trade.steam_offer_id == "7712345678"
    assert result.trade.seller_name is None


def test_lisskins_order_has_offer_id_no_seller_name(order: Order) -> None:
    """A LIS-SKINS order returns steam_offer_id but no seller_name."""
    purchase = LisskinsPurchase(
        order_id=order.id,
        custom_id="cid123",
        skin_id=12345,
        paid_units=10_000,
        steam_trade_offer_id="7712345679",
    )
    result = public_order(order, None, purchase)
    assert result.trade is not None
    assert result.trade.steam_offer_id == "7712345679"
    assert result.trade.seller_name is None


def test_waxpeer_order_has_offer_id_and_seller_name(order: Order) -> None:
    """A Waxpeer order returns both steam_offer_id and seller_name."""
    trade = SkinTrade(
        order_id=order.id,
        project_id="proj123",
        listing_id=999,
        paid_units=10_000,
        trade_id="7712345680",
        seller={"name": "bob", "level": 5},
    )
    result = public_order(order, trade, None)
    assert result.trade is not None
    assert result.trade.steam_offer_id == "7712345680"
    assert result.trade.seller_name == "bob"


def test_order_buying_has_no_trade_fields(order: Order) -> None:
    """An order still in 'buying' status has no trade object."""
    order.status = "buying"
    trade = SkinTrade(
        order_id=order.id,
        project_id="proj123",
        listing_id=999,
        paid_units=10_000,
        trade_id="7712345680",
        seller={"name": "bob"},
    )
    result = public_order(order, trade, None)
    # In buying state, trade should be None even though one exists
    assert result.trade is None
