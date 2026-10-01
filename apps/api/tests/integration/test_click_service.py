"""``click_transactions`` and the Click handlers (``prepare``, ``complete``, ``cancel``)
against a real Postgres: states, codes, replays, the insert race and the money-safety
guards (one credit per top-up, a second charge refused, a sibling's settled attempt never
pulled back). The route's signature layer is tested in ``test_click_webhook.py``."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.modules.click import service as click_svc
from csmarket.modules.click.errors import ClickError
from csmarket.modules.click.models import ClickTransaction
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending, settle
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_topup

SERVICE_ID = 108149
AMOUNT = Decimal(50000)
AMOUNT_STR = "50000.00"


async def _attempt(db: AsyncSession, topup: WalletTopup, provider: str = "click") -> Payment:
    payment = await ensure_attempt(
        db, payable=await resolve(db, topup.number, lock=True), provider=provider
    )
    await db.commit()
    return payment


async def _txn(db: AsyncSession, click_trans_id: int) -> ClickTransaction:
    stmt = (
        select(ClickTransaction)
        .where(ClickTransaction.click_trans_id == click_trans_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _payment(db: AsyncSession, payment_id: str) -> Payment:
    stmt = select(Payment).where(Payment.id == payment_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _prepare(
    db: AsyncSession, topup: WalletTopup, trans_id: int, **overrides: Any
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "click_trans_id": trans_id,
        "service_id": SERVICE_ID,
        "click_paydoc_id": trans_id + 5000,
        "merchant_trans_id": topup.number,
        "amount": AMOUNT_STR,
        **overrides,
    }
    result = await click_svc.prepare(db, **kwargs)
    await db.commit()
    return dict(result)


async def _complete(
    db: AsyncSession, topup: WalletTopup, trans_id: int, prepared: dict[str, Any], **kw: Any
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "click_trans_id": trans_id,
        "service_id": SERVICE_ID,
        "merchant_trans_id": topup.number,
        "merchant_prepare_id": prepared["merchant_prepare_id"],
        "amount": AMOUNT_STR,
        **kw,
    }
    result = await click_svc.complete(db, **kwargs)
    await db.commit()
    return dict(result)


async def _code(coro: Any) -> ClickError:
    with pytest.raises(ClickError) as exc:
        await coro
    return exc.value


# ---------- model ----------


async def test_click_transaction_round_trips(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    payment = await _attempt(db_session, topup)
    txn = ClickTransaction(
        click_trans_id=4_294_967_295,
        service_id=SERVICE_ID,
        payment_id=payment.id,
        account=topup.number,
        amount=AMOUNT,
        status="PREPARED",
    )
    db_session.add(txn)
    await db_session.flush()
    assert isinstance(txn.merchant_prepare_id, int)
    assert txn.merchant_prepare_id > 0
    fetched = await _txn(db_session, 4_294_967_295)
    assert (fetched.account, fetched.amount, fetched.status) == (topup.number, AMOUNT, "PREPARED")
    assert fetched.click_paydoc_id is None
    assert fetched.prepare_time is None
    assert fetched.created_at is not None


async def test_click_transaction_rejects_duplicate_trans_service(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    payment = await _attempt(db_session, topup)
    for _ in range(2):
        db_session.add(
            ClickTransaction(
                click_trans_id=111,
                service_id=SERVICE_ID,
                payment_id=payment.id,
                account=topup.number,
                amount=AMOUNT,
                status="PREPARED",
            )
        )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_click_transaction_status_check_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    payment = await _attempt(db_session, topup)
    db_session.add(
        ClickTransaction(
            click_trans_id=222,
            service_id=SERVICE_ID,
            payment_id=payment.id,
            account=topup.number,
            amount=AMOUNT,
            status="BOGUS",
        )
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()


# ---------- prepare ----------


async def test_prepare_creates_prepared_and_holds_an_attempt(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    result = await _prepare(db_session, topup, 1001)
    assert result["click_trans_id"] == 1001
    assert result["merchant_trans_id"] == topup.number
    assert isinstance(result["merchant_prepare_id"], int)
    assert (result["error"], result["error_note"]) == (0, "Success")

    row = await _txn(db_session, 1001)
    assert row.status == "PREPARED"
    assert row.merchant_prepare_id == result["merchant_prepare_id"]
    assert (row.click_paydoc_id, row.amount, row.account) == (6001, AMOUNT, topup.number)
    assert row.prepare_time is not None
    payment = await _payment(db_session, row.payment_id)
    assert (payment.provider, payment.status) == ("click", "pending")
    assert payment.provider_ref == f"click:{topup.number}"


async def test_prepare_replay_returns_same_prepare_id(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    first = await _prepare(db_session, topup, 1002)
    second = await _prepare(db_session, topup, 1002)
    assert second == first
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(ClickTransaction)
            .where(ClickTransaction.click_trans_id == 1002)
        )
    ).scalar_one()
    assert count == 1


async def test_prepare_concurrent_insert_race_returns_winners_id(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rival insert of the same ``(click_trans_id, service_id)`` lands after our pre-check:
    the real unique constraint collides in the SAVEPOINT and we answer the winner's id."""
    topup = await make_topup(db_session)
    payment = await _attempt(db_session, topup)
    winner = ClickTransaction(
        click_trans_id=1003,
        service_id=SERVICE_ID,
        payment_id=payment.id,
        account=topup.number,
        amount=AMOUNT,
        status="PREPARED",
        prepare_time=clock.now(),
    )
    db_session.add(winner)
    await db_session.commit()

    real = click_svc._txn_by_click
    calls = {"n": 0}

    async def first_call_misses(*args: Any, **kwargs: Any) -> ClickTransaction | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(click_svc, "_txn_by_click", first_call_misses)
    result = await _prepare(db_session, topup, 1003)
    assert result["merchant_prepare_id"] == winner.merchant_prepare_id
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(ClickTransaction)
            .where(ClickTransaction.click_trans_id == 1003)
        )
    ).scalar_one()
    assert count == 1


async def test_prepare_insert_race_for_another_account_leaves_no_pending_attempt(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two first-time prepares with one ``click_trans_id`` but different accounts lock
    different top-ups, so both reach the insert. The loser answers the winner's row (Click's
    replay contract) and its own attempt is not left ``pending`` with no Click row holding it
    (the attempt work sits in the insert's SAVEPOINT)."""
    winner_topup, loser_topup = await make_topup(db_session), await make_topup(db_session)
    loser_id = loser_topup.id
    winner = await _prepare(db_session, winner_topup, 1004)
    opened_id = (await _attempt(db_session, loser_topup)).id

    real = click_svc._txn_by_click
    calls = {"n": 0}

    async def first_call_misses(*args: Any, **kwargs: Any) -> ClickTransaction | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(click_svc, "_txn_by_click", first_call_misses)
    result = await _prepare(db_session, loser_topup, 1004)
    assert result == winner
    attempts = (
        (
            await db_session.execute(
                select(Payment)
                .where(Payment.topup_id == loser_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    assert [(p.id, p.status) for p in attempts] == [(opened_id, "created")]


@pytest.mark.parametrize("amount", ["49999.00", "50001", "abc", "NaN", "Infinity", "sNaN"])
async def test_prepare_wrong_amount_is_minus2(db_session: AsyncSession, amount: str) -> None:
    topup = await make_topup(db_session)
    err = await _code(_prepare(db_session, topup, 1004, amount=amount))
    assert err.code == -2


async def test_amount_in_soum_not_tiyin(db_session: AsyncSession) -> None:
    """Click speaks soʻm: the top-up's amount × 100 (tiyin) is a wrong amount."""
    topup = await make_topup(db_session)
    err = await _code(_prepare(db_session, topup, 1011, amount=str(AMOUNT * 100)))
    assert err.code == -2
    assert (await _prepare(db_session, topup, 1012, amount="50000"))["error"] == 0


@pytest.mark.parametrize("account", ["T0000000", "ORDER-1", ""])
async def test_prepare_unknown_account_is_minus5(db_session: AsyncSession, account: str) -> None:
    err = await _code(
        click_svc.prepare(
            db_session,
            click_trans_id=1005,
            service_id=SERVICE_ID,
            click_paydoc_id=5005,
            merchant_trans_id=account,
            amount=AMOUNT_STR,
        )
    )
    assert err.code == -5


async def test_a_second_prepare_on_a_paid_topup_is_minus4(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session, status="succeeded")
    err = await _code(_prepare(db_session, topup, 1006))
    assert err.code == -4
    assert err.persist is False
    assert (await db_session.execute(select(ClickTransaction))).first() is None


@pytest.mark.parametrize("status", ["expired", "reversed"])
async def test_prepare_on_an_unpayable_topup_is_minus9(
    db_session: AsyncSession, status: str
) -> None:
    topup = await make_topup(db_session, status=status)
    assert (await _code(_prepare(db_session, topup, 1007))).code == -9


async def test_prepare_past_expires_at_is_minus9(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session, expires_at=clock.now() - timedelta(seconds=1))
    assert (await _code(_prepare(db_session, topup, 1008))).code == -9


# ---------- complete ----------


async def test_complete_settles_and_credits_the_topup(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 2001)
    result = await _complete(db_session, topup, 2001, prepared)
    assert result == {
        "click_trans_id": 2001,
        "merchant_trans_id": topup.number,
        "merchant_confirm_id": prepared["merchant_prepare_id"],
        "error": 0,
        "error_note": "Success",
    }
    row = await _txn(db_session, 2001)
    assert row.status == "CONFIRMED"
    assert row.complete_time is not None
    payment = await _payment(db_session, row.payment_id)
    assert payment.status == "succeeded"
    assert payment.extra_metadata["settle_event_id"] == "click:2001"
    await db_session.refresh(topup)
    assert (topup.status, topup.payment_id) == ("succeeded", payment.id)
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_complete_after_expires_at_still_credits(db_session: AsyncSession) -> None:
    """Click held the top-up before it expired; the money arrived — it is credited."""
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 2006)
    topup.expires_at = clock.now() - timedelta(minutes=1)
    await db_session.commit()
    assert (await _complete(db_session, topup, 2006, prepared))["error"] == 0
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_complete_unknown_prepare_id_is_minus6(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    err = await _code(_complete(db_session, topup, 2002, {"merchant_prepare_id": 999_999_999}))
    assert err.code == -6


@pytest.mark.parametrize(
    "mismatch",
    [{"click_trans_id": 9}, {"service_id": 108150}, {"merchant_trans_id": "T0000000"}],
)
async def test_complete_with_mismatched_identifiers_is_minus6(
    db_session: AsyncSession, mismatch: dict[str, Any]
) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 2007)
    err = await _code(_complete(db_session, topup, 2007, prepared, **mismatch))
    assert err.code == -6


async def test_complete_replay_is_minus4_and_credits_once(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 2003)
    await _complete(db_session, topup, 2003, prepared)
    err = await _code(_complete(db_session, topup, 2003, prepared))
    assert (err.code, err.persist) == (-4, False)
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_complete_on_cancelled_is_minus9(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 2004)
    await click_svc.cancel(db_session, merchant_prepare_id=prepared["merchant_prepare_id"])
    await db_session.commit()
    assert (await _code(_complete(db_session, topup, 2004, prepared))).code == -9


async def test_complete_amount_mismatch_is_minus2(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 2005)
    err = await _code(_complete(db_session, topup, 2005, prepared, amount="49999.00"))
    assert err.code == -2


async def test_a_complete_after_the_topup_was_paid_by_another_kassa_is_refused(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 2101)
    other = await _attempt(db_session, topup, "mock")
    await mark_pending(db_session, payment=other)
    await settle(db_session, payment=other, event_id="mock:1")
    await db_session.commit()

    err = await _code(_complete(db_session, topup, 2101, prepared))
    assert (err.code, err.persist) == (-4, True)
    await db_session.commit()  # what the route does for a persisting error
    row = await _txn(db_session, 2101)
    assert row.status == "CANCELLED"
    assert (await _payment(db_session, row.payment_id)).status == "cancelled"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_a_sibling_complete_on_a_shared_attempt_is_refused(db_session: AsyncSession) -> None:
    """Two Click checkouts on one top-up share one live attempt. The first complete settles
    it; the second must not answer success (Click would charge twice for one credit)."""
    topup = await make_topup(db_session)
    a = await _prepare(db_session, topup, 2201)
    b = await _prepare(db_session, topup, 2202)
    row_a, row_b = await _txn(db_session, 2201), await _txn(db_session, 2202)
    assert row_a.payment_id == row_b.payment_id
    await _complete(db_session, topup, 2202, b)

    err = await _code(_complete(db_session, topup, 2201, a))
    assert (err.code, err.persist) == (-4, True)
    await db_session.commit()
    assert (await _txn(db_session, 2201)).status == "CANCELLED"
    assert (await _payment(db_session, row_a.payment_id)).status == "succeeded"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


# ---------- cancel ----------


async def test_cancel_from_prepared_cancels_the_attempt(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 3001)
    await click_svc.cancel(db_session, merchant_prepare_id=prepared["merchant_prepare_id"])
    await db_session.commit()
    row = await _txn(db_session, 3001)
    assert row.status == "CANCELLED"
    assert row.cancel_time is not None
    assert (await _payment(db_session, row.payment_id)).status == "cancelled"
    await db_session.refresh(topup)
    assert topup.status == "pending"


async def test_cancel_by_click_trans_id_and_service_id(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _prepare(db_session, topup, 3002)
    await click_svc.cancel(db_session, click_trans_id=3002, service_id=SERVICE_ID)
    await db_session.commit()
    assert (await _txn(db_session, 3002)).status == "CANCELLED"


async def test_cancel_requires_a_lookup_key(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="merchant_prepare_id"):
        await click_svc.cancel(db_session)


async def test_cancel_of_nothing_is_a_noop(db_session: AsyncSession) -> None:
    await click_svc.cancel(db_session, merchant_prepare_id=123_456_789)
    await click_svc.cancel(db_session, click_trans_id=1, service_id=SERVICE_ID)


async def test_cancel_twice_is_a_noop(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 3003)
    for _ in range(2):
        await click_svc.cancel(db_session, merchant_prepare_id=prepared["merchant_prepare_id"])
        await db_session.commit()
    assert (await _txn(db_session, 3003)).status == "CANCELLED"


async def test_cancel_leaves_a_confirmed_transaction_alone(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 3004)
    await _complete(db_session, topup, 3004, prepared)
    await click_svc.cancel(db_session, merchant_prepare_id=prepared["merchant_prepare_id"])
    await db_session.commit()
    row = await _txn(db_session, 3004)
    assert row.status == "CONFIRMED"
    assert (await _payment(db_session, row.payment_id)).status == "succeeded"


async def test_cancel_with_a_confirmed_sibling_leaves_the_settled_attempt(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    a = await _prepare(db_session, topup, 3005)
    b = await _prepare(db_session, topup, 3006)
    await _complete(db_session, topup, 3006, b)
    await click_svc.cancel(db_session, merchant_prepare_id=a["merchant_prepare_id"])
    await db_session.commit()
    row_a = await _txn(db_session, 3005)
    assert row_a.status == "CANCELLED"
    assert (await _payment(db_session, row_a.payment_id)).status == "succeeded"
    await db_session.refresh(topup)
    assert topup.status == "succeeded"


async def test_cancel_with_a_prepared_sibling_keeps_the_attempt_payable(
    db_session: AsyncSession,
) -> None:
    """Click aborts one of two checkouts sharing an attempt: the other can still pay."""
    topup = await make_topup(db_session)
    a = await _prepare(db_session, topup, 3007)
    b = await _prepare(db_session, topup, 3008)
    await click_svc.cancel(db_session, merchant_prepare_id=a["merchant_prepare_id"])
    await db_session.commit()
    row_b = await _txn(db_session, 3008)
    assert (await _payment(db_session, row_b.payment_id)).status == "pending"
    assert (await _complete(db_session, topup, 3008, b))["error"] == 0
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_a_new_prepare_after_a_cancelled_one_can_pay(db_session: AsyncSession) -> None:
    """A declined card, then a retry: the cancelled attempt's ``click:<number>`` reference
    must not turn the new prepare into a system error."""
    topup = await make_topup(db_session)
    first = await _prepare(db_session, topup, 3101)
    await click_svc.cancel(db_session, merchant_prepare_id=first["merchant_prepare_id"])
    await db_session.commit()
    second = await _prepare(db_session, topup, 3102)
    assert second["merchant_prepare_id"] != first["merchant_prepare_id"]
    assert (await _complete(db_session, topup, 3102, second))["error"] == 0
    row = await _txn(db_session, 3102)
    payment = await _payment(db_session, row.payment_id)
    assert payment.provider_ref == f"click:{topup.number}:{payment.id}"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


# ---------- lock order: top-up → Click row → payment ----------


@pytest.mark.parametrize("call", ["prepare_replay", "complete", "cancel"])
async def test_handlers_lock_the_topup_before_the_click_row(
    db_engine: AsyncEngine, call: str
) -> None:
    """A holder takes the top-up, the handler starts, then the holder takes the Click row
    (what the timeout sweep does). A handler that locked the row before the top-up would
    deadlock here; with the global order it just waits, then finishes."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        topup = await make_topup(setup)
        prepared = await _prepare(setup, topup, 4001)

    async def handler() -> None:
        async with factory() as db:
            if call == "prepare_replay":
                await click_svc.prepare(
                    db,
                    click_trans_id=4001,
                    service_id=SERVICE_ID,
                    click_paydoc_id=9001,
                    merchant_trans_id=topup.number,
                    amount=AMOUNT_STR,
                )
            elif call == "complete":
                await click_svc.complete(
                    db,
                    click_trans_id=4001,
                    service_id=SERVICE_ID,
                    merchant_trans_id=topup.number,
                    merchant_prepare_id=prepared["merchant_prepare_id"],
                    amount=AMOUNT_STR,
                )
            else:
                await click_svc.cancel(db, merchant_prepare_id=prepared["merchant_prepare_id"])
            await db.commit()

    async with factory() as holder:
        await resolve(holder, topup.number, lock=True)
        task = asyncio.create_task(handler())
        await asyncio.sleep(0.3)
        assert not task.done()  # waiting on the top-up, holding nothing else
        await holder.execute(
            select(ClickTransaction.id)
            .where(ClickTransaction.click_trans_id == 4001)
            .with_for_update()
        )
        await holder.commit()
    await asyncio.wait_for(task, timeout=10)
