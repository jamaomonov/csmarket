"""The sales tables: constraints that keep a sale, its card and its request consistent."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.sales.models import PayoutRequest, SaleItem
from csmarket.modules.wallet.models import WalletAccount
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import make_card, make_request, make_sale

pytestmark = pytest.mark.asyncio


async def test_a_sale_and_its_items_round_trip(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session)
    items = (
        await db_session.scalars(
            select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.asset_id)
        )
    ).all()
    assert [(i.asset_id, i.price_uzs) for i in items] == [("100", 149_600), ("101", 5_600)]
    assert sale.number.startswith("S")
    assert sale.items_uzs == Decimal(155_200)


async def test_a_card_sale_needs_a_card(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(IntegrityError):
        await make_sale(db_session, user=user, payout_to="card", payout_card_id=None)


async def test_a_balance_sale_takes_no_card(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    card = await make_card(db_session, user)
    with pytest.raises(IntegrityError):
        await make_sale(db_session, user=user, payout_to="balance", payout_card_id=card.id)


async def test_one_idempotency_key_per_user(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session)
    with pytest.raises(IntegrityError):
        # ``user_id`` through ``**over`` makes the second sale the same user's.
        await make_sale(db_session, user_id=sale.user_id, idempotency_key=sale.idempotency_key)


async def test_one_payout_request_per_sale(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, payout_to="card", status="payout")
    await make_request(db_session, sale)
    with pytest.raises(IntegrityError):
        await make_request(db_session, sale)


async def test_a_request_status_outside_the_set_is_refused(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, payout_to="card", status="payout")
    with pytest.raises(IntegrityError):
        await make_request(db_session, sale, status="sent")


async def test_house_skin_buys_is_an_account_kind(db_session: AsyncSession) -> None:
    db_session.add(
        WalletAccount(id=new_id(), owner_type="house", owner_id="house", kind="house_skin_buys")
    )
    await db_session.commit()


async def test_a_sale_letter_is_unique_per_sale_and_kind(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session)
    for _ in range(2):
        db_session.add(
            EmailOutbox(kind="sale_hold", user_id=sale.user_id, sale_id=sale.id, payload={})
        )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_a_request_points_at_its_card(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, payout_to="card", status="hold")
    request = await make_request(db_session, sale, status="waiting_hold")
    stored = await db_session.get(PayoutRequest, request.id)
    assert stored is not None
    assert (stored.card_id, stored.amount_uzs, stored.fee_uzs) == (
        sale.payout_card_id,
        sale.payout_uzs,
        sale.items_uzs - sale.payout_uzs,
    )
