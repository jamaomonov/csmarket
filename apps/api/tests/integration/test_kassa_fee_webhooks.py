"""Payme, Click and Uzum charge the payable plus the kassa fee frozen on the attempt; the
balance gets the base, a refund the price (spec 2026-10-14-kassa-fee). Every key is fake."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from csmarket.modules.click import service as click_svc
from csmarket.modules.click.errors import ClickError
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.payme import service as payme_svc
from csmarket.modules.payme.errors import PaymeError
from csmarket.modules.uzum import service as uzum_svc
from csmarket.modules.uzum.errors import UzumError
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.kassa_fee_factory import set_fees
from tests.integration.orders_factory import make_order
from tests.integration.payments_factory import make_topup
from tests.integration.test_click_service import SERVICE_ID as CLICK_SERVICE
from tests.integration.test_uzum_service import SERVICE_ID as UZUM_SERVICE
from tests.integration.test_uzum_service import SOURCE

BASE = Decimal(100000)
TIME = 1_790_000_000_000


async def _fails(coro: Any) -> int:
    with pytest.raises((PaymeError, ClickError, UzumError)) as exc:
        await coro
    err = exc.value
    assert isinstance(err, PaymeError | ClickError | UzumError)
    return int(err.code)


async def test_payme_wants_the_total(db_session: AsyncSession) -> None:
    await set_fees(db_session, payme="1")
    topup = await make_topup(db_session, amount=BASE)
    account = {"order": topup.number}
    check = payme_svc.check_perform_transaction
    assert await _fails(check(db_session, amount=10_000_000, account=account)) == -31001
    assert await check(db_session, amount=10_100_000, account=account) == {"allow": True}


async def test_payme_create_and_perform_credit_the_base(db_session: AsyncSession) -> None:
    await set_fees(db_session, payme="1")
    topup = await make_topup(db_session, amount=BASE)
    await payme_svc.create_transaction(
        db_session, payme_id="f" * 24, time=TIME, amount=10_100_000, account={"order": topup.number}
    )
    await db_session.commit()
    await payme_svc.perform_transaction(db_session, payme_id="f" * 24)
    await db_session.commit()
    assert await user_balance(db_session, topup.user_id) == BASE


async def test_a_rate_change_after_create_keeps_the_old_total(db_session: AsyncSession) -> None:
    await set_fees(db_session, payme="1")
    topup = await make_topup(db_session, amount=BASE)
    account = {"order": topup.number}
    await payme_svc.create_transaction(
        db_session, payme_id="g" * 24, time=TIME, amount=10_100_000, account=account
    )
    await db_session.commit()
    await set_fees(db_session, payme="2")
    check = payme_svc.check_perform_transaction
    assert await check(db_session, amount=10_100_000, account=account) == {"allow": True}
    assert await _fails(check(db_session, amount=10_200_000, account=account)) == -31001


async def test_click_prepares_and_completes_the_total(db_session: AsyncSession) -> None:
    await set_fees(db_session, click="1")
    topup = await make_topup(db_session, amount=BASE)
    user_id = topup.user_id  # read before the rollback expires the row
    common: dict[str, Any] = {
        "service_id": CLICK_SERVICE,
        "merchant_trans_id": topup.number,
    }
    bare = click_svc.prepare(
        db_session, click_trans_id=7001, click_paydoc_id=9001, amount="100000.00", **common
    )
    assert await _fails(bare) == -2
    await db_session.rollback()
    prepared = await click_svc.prepare(
        db_session, click_trans_id=7002, click_paydoc_id=9002, amount="101000.00", **common
    )
    await db_session.commit()
    assert prepared["error"] == 0
    done = await click_svc.complete(
        db_session,
        click_trans_id=7002,
        merchant_prepare_id=int(prepared["merchant_prepare_id"]),
        amount="101000.00",
        **common,
    )
    await db_session.commit()
    assert done["error"] == 0
    assert await user_balance(db_session, user_id) == BASE


async def test_uzum_reports_and_wants_the_total(db_session: AsyncSession) -> None:
    await set_fees(db_session, uzum="1")
    topup = await make_topup(db_session, amount=BASE)
    number, user_id = topup.number, topup.user_id  # read before the rollback expires the row
    checked = await uzum_svc.check(db_session, account=number)
    assert checked["data"]["amount"]["value"] == "101000"
    create = uzum_svc.create
    bare = create(
        db_session,
        service_id=UZUM_SERVICE,
        trans_id="u-bare",
        account=number,
        amount=10_000_000,
    )
    assert await _fails(bare) == 10011
    await db_session.rollback()
    await create(
        db_session,
        service_id=UZUM_SERVICE,
        trans_id="u-full",
        account=number,
        amount=10_100_000,
    )
    await db_session.commit()
    await uzum_svc.confirm(db_session, trans_id="u-full", payment_source=SOURCE)
    await db_session.commit()
    assert await user_balance(db_session, user_id) == BASE


async def test_an_order_is_paid_at_its_price_and_refunded_without_the_fee(
    db_session: AsyncSession,
) -> None:
    await set_fees(db_session, payme="1")
    order = await make_order(db_session, price_uzs=BASE)
    account = {"order": order.number}
    await payme_svc.create_transaction(
        db_session, payme_id="h" * 24, time=TIME, amount=10_100_000, account=account
    )
    await db_session.commit()
    await payme_svc.perform_transaction(db_session, payme_id="h" * 24)
    await db_session.commit()
    stmt = select(Order).where(Order.id == order.id).with_for_update()
    paid = (await db_session.execute(stmt.execution_options(populate_existing=True))).scalar_one()
    assert (paid.status, paid.paid_with, paid.price_uzs) == ("paid", "payme", BASE)
    paid.status = "buying"  # the worker's step; a buy that fails is refunded from here
    assert await refund_to_balance(
        db_session, order=paid, to_status="failed", reason="sold_out", actor="orders"
    )
    await db_session.commit()
    assert await user_balance(db_session, order.user_id) == BASE
