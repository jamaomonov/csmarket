"""The Uzum Merchant API handlers against a real Postgres: statuses, codes, replays, the
insert race and the money-safety guards (one credit per top-up, a second charge refused, a
spent top-up never reversed). The route's auth and envelope are tested in
``test_uzum_webhook.py``; the timeout sweep in ``test_uzum_timeout.py``."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending, settle
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.uzum import service as uzum_svc
from csmarket.modules.uzum.errors import UzumError
from csmarket.modules.uzum.models import UzumTransaction
from csmarket.modules.wallet.api import Leg, ensure_account, post, user_account, user_balance
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_topup

SERVICE_ID = 101202
AMOUNT = Decimal(50000)
TIYIN = 5_000_000
SOURCE = {"paymentSource": "UZCARD", "tariff": "003", "phone": "998000000000", "cardType": 2}


async def _create(
    db: AsyncSession,
    topup: WalletTopup,
    trans_id: str,
    *,
    amount: int = TIYIN,
    account: str | None = None,
) -> dict[str, Any]:
    result = await uzum_svc.create(
        db,
        service_id=SERVICE_ID,
        trans_id=trans_id,
        account=topup.number if account is None else account,
        amount=amount,
    )
    await db.commit()
    return dict(result)


async def _confirm(
    db: AsyncSession, trans_id: str, source: dict[str, Any] | None = None
) -> dict[str, Any]:
    result = await uzum_svc.confirm(
        db, trans_id=trans_id, payment_source=SOURCE if source is None else source
    )
    await db.commit()
    return dict(result)


async def _reverse(db: AsyncSession, trans_id: str) -> dict[str, Any]:
    result = await uzum_svc.reverse(db, trans_id=trans_id)
    await db.commit()
    return dict(result)


async def _code(coro: Any) -> UzumError:
    with pytest.raises(UzumError) as exc:
        await coro
    return exc.value


async def _txn(db: AsyncSession, trans_id: str) -> UzumTransaction:
    stmt = (
        select(UzumTransaction)
        .where(UzumTransaction.trans_id == trans_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _payment(db: AsyncSession, payment_id: str) -> Payment:
    stmt = select(Payment).where(Payment.id == payment_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _attempts(db: AsyncSession, topup_id: str) -> list[Payment]:
    stmt = (
        select(Payment)
        .where(Payment.topup_id == topup_id)
        .execution_options(populate_existing=True)
    )
    return list((await db.execute(stmt)).scalars())


async def _count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(UzumTransaction))).scalar_one())


async def _settle_elsewhere(db: AsyncSession, topup: WalletTopup) -> None:
    other = await ensure_attempt(
        db, payable=await resolve(db, topup.number, lock=True), provider="mock"
    )
    await mark_pending(db, payment=other)
    await settle(db, payment=other, event_id="mock:elsewhere")
    await db.commit()


async def _spend(db: AsyncSession, topup: WalletTopup, amount: Decimal) -> None:
    """Take ``amount`` off the balance (a stand-in for an M4 purchase)."""
    wallet = await user_account(db, topup.user_id)
    house = await ensure_account(
        db, owner_type="house", owner_id="house", kind="house_payments_received"
    )
    await post(
        db,
        kind="admin_adjust",
        legs=[Leg(wallet.id, "C", amount), Leg(house.id, "D", amount)],
        idempotency_key=f"spend:{topup.id}",
    )
    await db.commit()


def _first_call_misses() -> Callable[..., Awaitable[UzumTransaction | None]]:
    """``_txn_by_trans_id`` that misses once (the replay check ran before the winner
    committed), then reads for real (the re-read after the lost insert)."""
    real = uzum_svc._txn_by_trans_id
    calls = {"n": 0}

    async def lookup(db: AsyncSession, trans_id: str) -> UzumTransaction | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else await real(db, trans_id)

    return lookup


# ---------- /check ----------


async def test_check_returns_soum_value(db_session: AsyncSession) -> None:
    """``data.amount.value`` is whole soʻm as a bare integer string (Uzum prefills from it)."""
    topup = await make_topup(db_session, amount=Decimal(130000))
    result = await uzum_svc.check(db_session, account=topup.number)
    assert result == {"status": "OK", "data": {"amount": {"value": "130000"}}}


@pytest.mark.parametrize("account", ["T0000000", "X-1", "", "T" * 40])
async def test_check_unknown_account_is_10007(db_session: AsyncSession, account: str) -> None:
    assert (await _code(uzum_svc.check(db_session, account=account))).code == 10007


@pytest.mark.parametrize(("status", "code"), [("succeeded", 10008), ("expired", 10009)])
async def test_check_an_unpayable_topup(db_session: AsyncSession, status: str, code: int) -> None:
    topup = await make_topup(db_session, status=status)
    assert (await _code(uzum_svc.check(db_session, account=topup.number))).code == code


async def test_check_a_reversed_topup_is_10009(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session, status="reversed")
    assert (await _code(uzum_svc.check(db_session, account=topup.number))).code == 10009


async def test_check_past_expires_at_is_10009(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session, expires_at=clock.now() - timedelta(seconds=1))
    assert (await _code(uzum_svc.check(db_session, account=topup.number))).code == 10009


# ---------- /create ----------


async def test_create_creates_created_and_holds_an_attempt(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    before = uzum_svc.now_ms()
    result = await _create(db_session, topup, "uz-create")
    row = await _txn(db_session, "uz-create")
    assert result == {
        "transId": "uz-create",
        "status": "CREATED",
        "transTime": row.create_time,
        "amount": TIYIN,
    }
    assert row.create_time >= before
    assert (row.account, row.amount_tiyin, row.status, row.service_id) == (
        topup.number,
        TIYIN,
        "CREATED",
        SERVICE_ID,
    )
    assert (row.confirm_time, row.reverse_time, row.payment_source) == (None, None, {})
    payment = await _payment(db_session, row.payment_id)
    assert (payment.provider, payment.status) == ("uzum", "pending")
    assert payment.provider_ref == f"uzum:{topup.number}"


async def test_create_reuses_the_attempt_the_checkout_opened(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    opened = await ensure_attempt(
        db_session, payable=await resolve(db_session, topup.number, lock=True), provider="uzum"
    )
    await db_session.commit()
    await _create(db_session, topup, "uz-reuse")
    assert (await _txn(db_session, "uz-reuse")).payment_id == opened.id
    assert [p.status for p in await _attempts(db_session, topup.id)] == ["pending"]


async def test_a_second_create_on_a_topup_shares_the_attempt(db_session: AsyncSession) -> None:
    """A retried Uzum checkout opens a second transaction; both back the one live attempt."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-share-a")
    await _create(db_session, topup, "uz-share-b")
    a, b = await _txn(db_session, "uz-share-a"), await _txn(db_session, "uz-share-b")
    assert a.payment_id == b.payment_id
    assert len(await _attempts(db_session, topup.id)) == 1


async def test_create_replay_same_trans_id_is_10010(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-replay")
    assert (await _code(_create(db_session, topup, "uz-replay"))).code == 10010
    assert await _count(db_session) == 1


async def test_create_replay_after_confirm_is_still_10010(db_session: AsyncSession) -> None:
    """A late replay after the top-up was paid answers Uzum's replay code, not 10008."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-replay-late")
    await _confirm(db_session, "uz-replay-late")
    assert (await _code(_create(db_session, topup, "uz-replay-late"))).code == 10010


async def test_create_replay_for_another_account_is_10010_and_holds_nothing(
    db_session: AsyncSession,
) -> None:
    """Ruling 2: the id belongs to another top-up — refused (10010) without locking that row
    and without opening an attempt on the caller's top-up."""
    topup, other = await make_topup(db_session), await make_topup(db_session)
    await _create(db_session, topup, "uz-replay-account")
    err = await _code(_create(db_session, other, "uz-replay-account"))
    assert (err.code, err.persist) == (10010, False)
    assert await _attempts(db_session, other.id) == []
    assert (await _txn(db_session, "uz-replay-account")).account == topup.number


async def test_create_insert_race_for_another_account_leaves_no_pending_attempt(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two first-time ``/create`` calls with one ``transId`` but different accounts lock
    different top-ups, so both reach the insert. The loser answers 10010 and its attempt is
    not left ``pending`` (the attempt work sits in the insert's SAVEPOINT)."""
    winner_topup, loser_topup = await make_topup(db_session), await make_topup(db_session)
    winner_number, loser_id = winner_topup.number, loser_topup.id
    await _create(db_session, winner_topup, "uz-race")
    opened = await ensure_attempt(
        db_session,
        payable=await resolve(db_session, loser_topup.number, lock=True),
        provider="uzum",
    )
    opened_id = opened.id
    await db_session.commit()

    monkeypatch.setattr(uzum_svc, "_txn_by_trans_id", _first_call_misses())
    err = await _code(_create(db_session, loser_topup, "uz-race"))
    assert (err.code, err.persist) == (10010, False)
    # Undone by the SAVEPOINT already, not only by the route's rollback.
    attempts = await _attempts(db_session, loser_id)
    assert [(p.id, p.status) for p in attempts] == [(opened_id, "created")]
    await db_session.rollback()  # what the route does for a non-persisting refusal
    assert (await _txn(db_session, "uz-race")).account == winner_number
    assert await _count(db_session) == 1


async def test_create_insert_race_for_the_same_account_is_10010(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    topup_id = topup.id
    await _create(db_session, topup, "uz-race-same")

    monkeypatch.setattr(uzum_svc, "_txn_by_trans_id", _first_call_misses())
    assert (await _code(_create(db_session, topup, "uz-race-same"))).code == 10010
    await db_session.rollback()
    assert await _count(db_session) == 1
    assert [p.status for p in await _attempts(db_session, topup_id)] == ["pending"]


async def test_amount_in_tiyin(db_session: AsyncSession) -> None:
    """Uzum speaks tiyin on ``/create``: the soʻm figure is a wrong amount; × 100 is right."""
    topup = await make_topup(db_session)
    assert (await _code(_create(db_session, topup, "uz-soum", amount=50000))).code == 10011
    assert (await _create(db_session, topup, "uz-tiyin"))["amount"] == TIYIN


@pytest.mark.parametrize("amount", [TIYIN - 1, TIYIN + 1, 0, -TIYIN])
async def test_create_wrong_amount_is_10011(db_session: AsyncSession, amount: int) -> None:
    topup = await make_topup(db_session)
    assert (await _code(_create(db_session, topup, "uz-amount", amount=amount))).code == 10011
    assert await _count(db_session) == 0
    assert await _attempts(db_session, topup.id) == []


async def test_create_unknown_account_is_10007(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    err = await _code(_create(db_session, topup, "uz-unknown", account="T0000000"))
    assert err.code == 10007


async def test_create_on_a_paid_topup_is_10008(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session, status="succeeded")
    assert (await _code(_create(db_session, topup, "uz-paid"))).code == 10008
    assert await _attempts(db_session, topup.id) == []


@pytest.mark.parametrize("status", ["expired", "reversed"])
async def test_create_on_an_unpayable_topup_is_10009(db_session: AsyncSession, status: str) -> None:
    topup = await make_topup(db_session, status=status)
    assert (await _code(_create(db_session, topup, "uz-gone"))).code == 10009


# ---------- /confirm ----------


async def test_confirm_settles_and_credits_the_topup(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-confirm")
    result = await _confirm(db_session, "uz-confirm")
    row = await _txn(db_session, "uz-confirm")
    assert result == {
        "transId": "uz-confirm",
        "status": "CONFIRMED",
        "confirmTime": row.confirm_time,
        "amount": TIYIN,
    }
    assert row.confirm_time is not None
    assert row.confirm_time >= row.create_time
    assert row.payment_source == SOURCE
    payment = await _payment(db_session, row.payment_id)
    assert payment.status == "succeeded"
    assert payment.extra_metadata["settle_event_id"] == "uzum:uz-confirm"
    await db_session.refresh(topup)
    assert (topup.status, topup.payment_id) == ("succeeded", payment.id)
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_confirm_replay_is_10016_and_credits_once(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    user_id = topup.user_id
    await _create(db_session, topup, "uz-confirm-replay")
    await _confirm(db_session, "uz-confirm-replay")
    assert (await _code(_confirm(db_session, "uz-confirm-replay"))).code == 10016
    await db_session.rollback()
    assert await user_balance(db_session, user_id) == AMOUNT


async def test_confirm_after_expires_at_still_credits(db_session: AsyncSession) -> None:
    """Uzum held the top-up before it expired; the money arrived — it is credited."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-late")
    topup.expires_at = clock.now() - timedelta(minutes=1)
    await db_session.commit()
    assert (await _confirm(db_session, "uz-late"))["status"] == "CONFIRMED"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_confirm_unknown_is_10014(db_session: AsyncSession) -> None:
    assert (await _code(_confirm(db_session, "nope"))).code == 10014


@pytest.mark.parametrize("status", ["REVERSED", "FAILED"])
async def test_confirm_on_a_closed_transaction_is_10015(
    db_session: AsyncSession, status: str
) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-closed")
    row = await _txn(db_session, "uz-closed")
    row.status = status
    await db_session.commit()
    err = await _code(_confirm(db_session, "uz-closed"))
    assert (err.code, err.persist) == (10015, False)


async def test_confirm_after_paid_elsewhere_is_10008(db_session: AsyncSession) -> None:
    """Ruling 3: the top-up was credited through another kassa while Uzum held it — this
    charge is a second one. 10008, and the transaction is FAILED and kept (persist)."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-elsewhere")
    await _settle_elsewhere(db_session, topup)

    err = await _code(_confirm(db_session, "uz-elsewhere"))
    assert (err.code, err.persist) == (10008, True)
    await db_session.commit()  # what the route does for a persisting refusal
    row = await _txn(db_session, "uz-elsewhere")
    assert (row.status, row.confirm_time) == ("FAILED", None)
    assert (await _payment(db_session, row.payment_id)).status == "cancelled"
    assert await user_balance(db_session, topup.user_id) == AMOUNT
    status = await uzum_svc.status(db_session, trans_id="uz-elsewhere")
    assert status["status"] == "FAILED"


async def test_confirm_on_an_attempt_a_sibling_settled_is_10008(db_session: AsyncSession) -> None:
    """Two Uzum rows share one attempt; once one confirms, the other's confirm must not
    answer success for the settled attempt (Uzum would charge twice)."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-sib-a")
    await _create(db_session, topup, "uz-sib-b")
    payment_id = (await _txn(db_session, "uz-sib-a")).payment_id
    await _confirm(db_session, "uz-sib-a")
    err = await _code(_confirm(db_session, "uz-sib-b"))
    assert (err.code, err.persist) == (10008, True)
    await db_session.commit()
    assert (await _txn(db_session, "uz-sib-b")).status == "FAILED"
    assert (await _payment(db_session, payment_id)).status == "succeeded"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


# ---------- /reverse ----------


async def test_reverse_created_releases_the_attempt(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-rev-created")
    result = await _reverse(db_session, "uz-rev-created")
    row = await _txn(db_session, "uz-rev-created")
    assert result == {
        "transId": "uz-rev-created",
        "status": "REVERSED",
        "reverseTime": row.reverse_time,
        "amount": TIYIN,
    }
    assert row.reverse_time is not None
    assert (await _payment(db_session, row.payment_id)).status == "cancelled"
    await db_session.refresh(topup)
    assert topup.status == "pending"
    assert await user_balance(db_session, topup.user_id) == 0


async def test_a_new_transaction_after_a_reversed_one_can_pay(db_session: AsyncSession) -> None:
    """Card declined: Uzum reverses the first transaction and the buyer retries — the new
    attempt gets its own reference (``uzum:<number>:<id>``), never a 99999."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-retry-1")
    await _reverse(db_session, "uz-retry-1")
    await _create(db_session, topup, "uz-retry-2")
    assert (await _confirm(db_session, "uz-retry-2"))["status"] == "CONFIRMED"
    payment = await _payment(db_session, (await _txn(db_session, "uz-retry-2")).payment_id)
    assert payment.provider_ref == f"uzum:{topup.number}:{payment.id}"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_reverse_confirmed_unspent_reverses_the_topup(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-rev-confirmed")
    await _confirm(db_session, "uz-rev-confirmed")
    assert (await _reverse(db_session, "uz-rev-confirmed"))["status"] == "REVERSED"
    row = await _txn(db_session, "uz-rev-confirmed")
    payment = await _payment(db_session, row.payment_id)
    assert payment.status == "refunded"
    assert payment.extra_metadata["reverse_event_id"] == "uzum:uz-rev-confirmed"
    await db_session.refresh(topup)
    assert topup.status == "reversed"
    assert await user_balance(db_session, topup.user_id) == 0


async def test_reverse_spent_topup_is_10017(db_session: AsyncSession) -> None:
    """Ruling R7: the money already left the balance — Uzum's reverse is refused."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-spent")
    await _confirm(db_session, "uz-spent")
    await _spend(db_session, topup, Decimal(10000))
    user_id = topup.user_id

    err = await _code(_reverse(db_session, "uz-spent"))
    assert (err.code, err.persist) == (10017, False)
    await db_session.rollback()
    row = await _txn(db_session, "uz-spent")
    assert (row.status, row.reverse_time) == ("CONFIRMED", None)
    assert (await _payment(db_session, row.payment_id)).status == "succeeded"
    assert await user_balance(db_session, user_id) == Decimal(40000)


async def test_reverse_replay_is_10018(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    user_id = topup.user_id
    await _create(db_session, topup, "uz-rev-replay")
    await _confirm(db_session, "uz-rev-replay")
    await _reverse(db_session, "uz-rev-replay")
    assert (await _code(_reverse(db_session, "uz-rev-replay"))).code == 10018
    await db_session.rollback()
    assert await user_balance(db_session, user_id) == 0


async def test_reverse_failed_closes_it_without_touching_the_attempt(
    db_session: AsyncSession,
) -> None:
    """A FAILED row (swept, or a refused second charge) already let its attempt go."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-rev-failed")
    await _settle_elsewhere(db_session, topup)
    await _code(_confirm(db_session, "uz-rev-failed"))
    await db_session.commit()
    assert (await _reverse(db_session, "uz-rev-failed"))["status"] == "REVERSED"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_reverse_unknown_is_10014(db_session: AsyncSession) -> None:
    assert (await _code(_reverse(db_session, "nope"))).code == 10014


async def test_reverse_with_a_created_sibling_keeps_the_attempt_payable(
    db_session: AsyncSession,
) -> None:
    """Ruling 4: a reverse releases a shared attempt only when no other CREATED row holds it."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-keep-a")
    await _create(db_session, topup, "uz-keep-b")
    payment_id = (await _txn(db_session, "uz-keep-a")).payment_id
    await _reverse(db_session, "uz-keep-a")
    assert (await _payment(db_session, payment_id)).status == "pending"
    assert (await _confirm(db_session, "uz-keep-b"))["status"] == "CONFIRMED"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_reverse_created_on_an_attempt_a_sibling_settled_leaves_it_alone(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-settled-a")
    await _create(db_session, topup, "uz-settled-b")
    payment_id = (await _txn(db_session, "uz-settled-a")).payment_id
    await _confirm(db_session, "uz-settled-a")
    assert (await _reverse(db_session, "uz-settled-b"))["status"] == "REVERSED"
    assert (await _payment(db_session, payment_id)).status == "succeeded"
    await db_session.refresh(topup)
    assert topup.status == "succeeded"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


# ---------- /status ----------


async def test_status_shape_through_the_lifecycle(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "uz-status")
    row = await _txn(db_session, "uz-status")
    expected = {
        "transId": "uz-status",
        "status": "CREATED",
        "transTime": row.create_time,
        "confirmTime": None,
        "reverseTime": None,
        "data": {},
        "amount": TIYIN,
    }
    assert await uzum_svc.status(db_session, trans_id="uz-status") == expected
    await _confirm(db_session, "uz-status")
    row = await _txn(db_session, "uz-status")
    expected |= {"status": "CONFIRMED", "confirmTime": row.confirm_time}
    assert await uzum_svc.status(db_session, trans_id="uz-status") == expected
    await _reverse(db_session, "uz-status")
    row = await _txn(db_session, "uz-status")
    expected |= {"status": "REVERSED", "reverseTime": row.reverse_time}
    assert await uzum_svc.status(db_session, trans_id="uz-status") == expected


async def test_status_unknown_is_10014(db_session: AsyncSession) -> None:
    assert (await _code(uzum_svc.status(db_session, trans_id="nope"))).code == 10014


# ---------- lock order: top-up → Uzum row → payment ----------


@pytest.mark.parametrize("call", ["create_replay", "confirm", "reverse"])
async def test_handlers_lock_the_topup_before_the_uzum_row(
    db_engine: AsyncEngine, call: str
) -> None:
    """A holder takes the top-up, the handler starts, then the holder takes the Uzum row
    (what the timeout sweep does). A handler that locked the row before the top-up would
    deadlock here; with the global order it just waits, then finishes."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        topup = await make_topup(setup)
        await _create(setup, topup, "uz-lock")

    async def handler() -> None:
        async with factory() as db:
            if call == "create_replay":
                with pytest.raises(UzumError):
                    await uzum_svc.create(
                        db,
                        service_id=SERVICE_ID,
                        trans_id="uz-lock",
                        account=topup.number,
                        amount=TIYIN,
                    )
            elif call == "confirm":
                await uzum_svc.confirm(db, trans_id="uz-lock", payment_source={})
            else:
                await uzum_svc.reverse(db, trans_id="uz-lock")
            await db.commit()

    async with factory() as holder:
        await resolve(holder, topup.number, lock=True)
        task = asyncio.create_task(handler())
        await asyncio.sleep(0.3)
        assert not task.done()  # waiting on the top-up, holding nothing else
        await holder.execute(
            select(UzumTransaction.id)
            .where(UzumTransaction.trans_id == "uz-lock")
            .with_for_update()
        )
        await holder.commit()
    await asyncio.wait_for(task, timeout=10)
