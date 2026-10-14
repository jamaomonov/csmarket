"""An attempt freezes the kassa's fee; the kassa page asks for the base plus the fee
(spec 2026-10-14-kassa-fee)."""

from __future__ import annotations

from decimal import Decimal

from csmarket.modules.payments.fees import kassa_charge
from csmarket.modules.payments.hooks import charge_of, ensure_attempt
from csmarket.modules.payments.payable import resolve
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.kassa_fee_factory import set_fees
from tests.integration.payments_factory import make_topup


async def test_a_new_attempt_freezes_todays_rate(db_session: AsyncSession) -> None:
    await set_fees(db_session, click="1", payme="1.5")
    topup = await make_topup(db_session, amount=Decimal(100000))
    payable = await resolve(db_session, topup.number, lock=True)
    payment = await ensure_attempt(db_session, payable=payable, provider="payme")
    assert (payment.amount_uzs, payment.fee_pct, payment.fee_uzs) == (
        Decimal(100000),
        Decimal("1.5"),
        Decimal(1500),
    )
    assert charge_of(payment) == Decimal(101500)


async def test_a_later_rate_does_not_move_the_live_attempt(db_session: AsyncSession) -> None:
    await set_fees(db_session, payme="1")
    topup = await make_topup(db_session, amount=Decimal(100000))
    payable = await resolve(db_session, topup.number, lock=True)
    first = await ensure_attempt(db_session, payable=payable, provider="payme")
    await db_session.commit()
    await set_fees(db_session, payme="3")
    payable = await resolve(db_session, topup.number, lock=True)
    again = await ensure_attempt(db_session, payable=payable, provider="payme")
    assert again.id == first.id
    assert again.fee_uzs == Decimal(1000)
    assert (await kassa_charge(db_session, payable, "payme")).total_uzs == Decimal(101000)


async def test_before_any_attempt_the_charge_is_todays_rate(db_session: AsyncSession) -> None:
    await set_fees(db_session, uzum="2")
    topup = await make_topup(db_session, amount=Decimal(100000))
    payable = await resolve(db_session, topup.number)
    charge = await kassa_charge(db_session, payable, "uzum")
    assert (charge.pct, charge.fee_uzs, charge.total_uzs) == (
        Decimal(2),
        Decimal(2000),
        Decimal(102000),
    )


async def test_each_kassa_has_its_own_fee_on_one_payable(db_session: AsyncSession) -> None:
    await set_fees(db_session, click="1", payme="2")
    topup = await make_topup(db_session, amount=Decimal(100000))
    payable = await resolve(db_session, topup.number, lock=True)
    click = await ensure_attempt(db_session, payable=payable, provider="click")
    payme = await ensure_attempt(db_session, payable=payable, provider="payme")
    assert (click.fee_uzs, payme.fee_uzs) == (Decimal(1000), Decimal(2000))


async def test_no_rate_no_fee(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session, amount=Decimal(50000))
    payable = await resolve(db_session, topup.number, lock=True)
    payment = await ensure_attempt(db_session, payable=payable, provider="click")
    assert payment.fee_uzs == 0
    assert charge_of(payment) == Decimal(50000)
