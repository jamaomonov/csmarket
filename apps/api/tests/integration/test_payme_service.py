"""The Payme Merchant API handlers against a real Postgres: states, codes, replays, the
insert race and the money-safety guards (one credit per top-up, a second charge refused, a
spent top-up never reversed). The route's auth and JSON-RPC layer is tested in
``test_payme_merchant.py``; the timeout sweep in ``test_payme_timeout.py``."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.modules.payme import service as payme_svc
from csmarket.modules.payme.errors import PaymeError
from csmarket.modules.payme.models import PaymeTransaction
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending, settle
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.wallet.api import Leg, ensure_account, post, user_account, user_balance
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_topup

AMOUNT = Decimal(50000)
TIYIN = 5_000_000
TIME = 1_790_000_000_000


async def _create(
    db: AsyncSession,
    topup: WalletTopup,
    payme_id: str,
    *,
    amount: int = TIYIN,
    time: int = TIME,
    account: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await payme_svc.create_transaction(
        db,
        payme_id=payme_id,
        time=time,
        amount=amount,
        account={"order": topup.number} if account is None else account,
    )
    await db.commit()
    return dict(result)


async def _perform(db: AsyncSession, payme_id: str) -> dict[str, Any]:
    result = await payme_svc.perform_transaction(db, payme_id=payme_id)
    await db.commit()
    return dict(result)


async def _cancel(db: AsyncSession, payme_id: str, reason: int = 1) -> dict[str, Any]:
    result = await payme_svc.cancel_transaction(db, payme_id=payme_id, reason=reason)
    await db.commit()
    return dict(result)


async def _code(coro: Any) -> PaymeError:
    with pytest.raises(PaymeError) as exc:
        await coro
    return exc.value


async def _txn(db: AsyncSession, payme_id: str) -> PaymeTransaction:
    stmt = (
        select(PaymeTransaction)
        .where(PaymeTransaction.payme_id == payme_id)
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


# ---------- CheckPerformTransaction ----------


async def test_check_perform_allows_a_payable_topup(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    result = await payme_svc.check_perform_transaction(
        db_session, amount=TIYIN, account={"order": topup.number}
    )
    assert result == {"allow": True}


async def test_amount_in_tiyin(db_session: AsyncSession) -> None:
    """Payme speaks tiyin: the top-up's amount in soʻm is a wrong amount; × 100 is right."""
    topup = await make_topup(db_session)
    account = {"order": topup.number}
    err = await _code(
        payme_svc.check_perform_transaction(db_session, amount=50000, account=account)
    )
    assert err.code == -31001
    result = await payme_svc.check_perform_transaction(db_session, amount=TIYIN, account=account)
    assert result == {"allow": True}


@pytest.mark.parametrize("amount", [TIYIN - 1, TIYIN + 1, 0])
async def test_check_perform_wrong_amount_is_31001(db_session: AsyncSession, amount: int) -> None:
    topup = await make_topup(db_session)
    err = await _code(
        payme_svc.check_perform_transaction(
            db_session, amount=amount, account={"order": topup.number}
        )
    )
    assert err.code == -31001


@pytest.mark.parametrize(
    "account",
    [{}, {"order": ""}, {"order": "   "}, {"order": 123}, {"order": "T0000000"}, {"order": "X-1"}],
)
async def test_check_perform_missing_or_unknown_account_is_31050(
    db_session: AsyncSession, account: dict[str, Any]
) -> None:
    err = await _code(
        payme_svc.check_perform_transaction(db_session, amount=TIYIN, account=account)
    )
    assert (err.code, err.data) == (-31050, "order")


@pytest.mark.parametrize("status", ["succeeded", "expired", "reversed"])
async def test_check_perform_on_an_unpayable_topup_is_31051(
    db_session: AsyncSession, status: str
) -> None:
    topup = await make_topup(db_session, status=status)
    err = await _code(
        payme_svc.check_perform_transaction(
            db_session, amount=TIYIN, account={"order": topup.number}
        )
    )
    assert (err.code, err.data) == (-31051, "order")


async def test_check_perform_past_expires_at_is_31051(db_session: AsyncSession) -> None:
    from datetime import timedelta

    topup = await make_topup(db_session, expires_at=clock.now() - timedelta(seconds=1))
    err = await _code(
        payme_svc.check_perform_transaction(
            db_session, amount=TIYIN, account={"order": topup.number}
        )
    )
    assert err.code == -31051


# ---------- CreateTransaction ----------


async def test_create_transaction_creates_state_1_and_holds_an_attempt(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    result = await _create(db_session, topup, "pt-create")
    row = await _txn(db_session, "pt-create")
    assert result == {"create_time": TIME, "transaction": row.id, "state": 1}
    assert (row.account, row.amount_tiyin, row.state, row.reason) == (topup.number, TIYIN, 1, None)
    assert (row.create_time, row.perform_time, row.cancel_time) == (TIME, 0, 0)
    payment = await _payment(db_session, row.payment_id)
    assert (payment.provider, payment.status) == ("payme", "pending")
    assert payment.provider_ref == f"payme:{topup.number}"


async def test_create_reuses_the_attempt_the_checkout_opened(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    opened = await ensure_attempt(
        db_session, payable=await resolve(db_session, topup.number, lock=True), provider="payme"
    )
    await db_session.commit()
    await _create(db_session, topup, "pt-reuse")
    row = await _txn(db_session, "pt-reuse")
    assert row.payment_id == opened.id
    assert [p.status for p in await _attempts(db_session, topup.id)] == ["pending"]


async def test_create_replay_is_idempotent_one_row(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    first = await _create(db_session, topup, "pt-replay")
    second = await _create(db_session, topup, "pt-replay", time=TIME + 999)
    assert second == first
    count = (
        await db_session.execute(select(func.count()).select_from(PaymeTransaction))
    ).scalar_one()
    assert count == 1


async def test_create_replay_after_perform_echoes_the_stored_state(
    db_session: AsyncSession,
) -> None:
    """A late replay of CreateTransaction after the top-up was paid echoes, never refuses."""
    topup = await make_topup(db_session)
    created = await _create(db_session, topup, "pt-replay-late")
    await _perform(db_session, "pt-replay-late")
    replay = await _create(db_session, topup, "pt-replay-late")
    assert replay == {**created, "state": 2}


async def test_create_replay_with_another_amount_is_31001(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-replay-amount")
    err = await _code(_create(db_session, topup, "pt-replay-amount", amount=TIYIN + 7))
    assert err.code == -31001


async def test_create_replay_for_another_account_is_31008(db_session: AsyncSession) -> None:
    topup, other = await make_topup(db_session), await make_topup(db_session)
    await _create(db_session, topup, "pt-replay-account")
    err = await _code(_create(db_session, other, "pt-replay-account"))
    assert err.code == -31008
    assert await _attempts(db_session, other.id) == []


async def test_create_wrong_amount_is_31001(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    assert (await _code(_create(db_session, topup, "pt-amount", amount=TIYIN - 5))).code == -31001
    assert (await db_session.execute(select(PaymeTransaction))).first() is None


async def test_create_unknown_account_is_31050(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    err = await _code(_create(db_session, topup, "pt-unknown", account={"order": "T0000000"}))
    assert err.code == -31050


async def test_create_on_a_paid_topup_is_31051(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session, status="succeeded")
    assert (await _code(_create(db_session, topup, "pt-paid"))).code == -31051
    assert await _attempts(db_session, topup.id) == []


async def test_create_second_active_transaction_on_a_topup_is_31099(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-active-a")
    err = await _code(_create(db_session, topup, "pt-active-b", time=TIME + 1))
    assert (err.code, err.data) == (-31099, "order")


async def test_a_new_transaction_after_a_cancelled_one_can_pay(db_session: AsyncSession) -> None:
    """Card declined (Payme cancels with reason 2), the buyer tries again: Payme opens a
    second transaction. YuPay, 2026-09-29: the retry hit the cancelled attempt's
    ``payme:<number>`` reference and answered −32400 («Сервис поставщика услуг недоступен»)."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-retry-1")
    await _cancel(db_session, "pt-retry-1", reason=2)
    second = await _create(db_session, topup, "pt-retry-2", time=TIME + 60_000)
    assert second["state"] == 1
    assert (await _perform(db_session, "pt-retry-2"))["state"] == 2
    row = await _txn(db_session, "pt-retry-2")
    payment = await _payment(db_session, row.payment_id)
    assert payment.provider_ref == f"payme:{topup.number}:{payment.id}"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_create_insert_race_for_another_account_leaves_no_pending_attempt(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two first-time CreateTransactions with one Payme id but different accounts lock
    different top-ups, so both reach the insert. The loser is refused and its attempt is
    not left ``pending`` (the attempt work sits in the insert's SAVEPOINT)."""
    winner_topup, loser_topup = await make_topup(db_session), await make_topup(db_session)
    winner_number, loser_id = winner_topup.number, loser_topup.id
    await _create(db_session, winner_topup, "pt-race")
    opened = await ensure_attempt(
        db_session,
        payable=await resolve(db_session, loser_topup.number, lock=True),
        provider="payme",
    )
    opened_id = opened.id
    await db_session.commit()

    real = payme_svc._txn_by_payme_id
    calls = {"n": 0}

    async def first_call_misses(*args: Any, **kwargs: Any) -> PaymeTransaction | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(payme_svc, "_txn_by_payme_id", first_call_misses)
    err = await _code(_create(db_session, loser_topup, "pt-race"))
    assert (err.code, err.persist) == (-31008, False)
    # Undone by the SAVEPOINT already, not only by the route's rollback.
    attempts = await _attempts(db_session, loser_id)
    assert [(p.id, p.status) for p in attempts] == [(opened_id, "created")]
    await db_session.rollback()  # what the route does for a non-persisting refusal
    assert (await _txn(db_session, "pt-race")).account == winner_number


async def test_create_replay_for_another_account_never_waits_on_that_row(
    db_engine: AsyncEngine,
) -> None:
    """A replayed id under another account is refused −31008 from an unlocked read: it must
    not lock (or wait on) a Payme row whose top-up it never took."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        owner, other = await make_topup(setup), await make_topup(setup)
        await _create(setup, owner, "pt-foreign")
    async with factory() as holder, factory() as caller:
        await holder.execute(
            select(PaymeTransaction.id)
            .where(PaymeTransaction.payme_id == "pt-foreign")
            .with_for_update()
        )
        call = payme_svc.create_transaction(
            caller, payme_id="pt-foreign", time=TIME, amount=TIYIN, account={"order": other.number}
        )
        with pytest.raises(PaymeError) as exc:
            await asyncio.wait_for(call, timeout=3)
        assert exc.value.code == -31008
        await caller.rollback()
        await holder.rollback()


async def test_create_insert_race_for_the_same_account_answers_the_winner(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topup = await make_topup(db_session)
    winner = await _create(db_session, topup, "pt-race-same")

    real = payme_svc._txn_by_payme_id
    calls = {"n": 0}

    async def first_call_misses(*args: Any, **kwargs: Any) -> PaymeTransaction | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(payme_svc, "_txn_by_payme_id", first_call_misses)
    assert await _create(db_session, topup, "pt-race-same") == winner
    count = (
        await db_session.execute(select(func.count()).select_from(PaymeTransaction))
    ).scalar_one()
    assert count == 1


# ---------- PerformTransaction ----------


async def test_perform_settles_and_credits_the_topup(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    created = await _create(db_session, topup, "pt-perform")
    result = await _perform(db_session, "pt-perform")
    row = await _txn(db_session, "pt-perform")
    assert result == {
        "transaction": created["transaction"],
        "perform_time": row.perform_time,
        "state": 2,
    }
    assert row.perform_time > TIME
    payment = await _payment(db_session, row.payment_id)
    assert payment.status == "succeeded"
    assert payment.extra_metadata["settle_event_id"] == "payme:pt-perform"
    await db_session.refresh(topup)
    assert (topup.status, topup.payment_id) == ("succeeded", payment.id)
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_perform_replay_is_idempotent_and_credits_once(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-perform-replay")
    first = await _perform(db_session, "pt-perform-replay")
    second = await _perform(db_session, "pt-perform-replay")
    assert first == second
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_perform_after_expires_at_still_credits(db_session: AsyncSession) -> None:
    """Payme held the top-up before it expired; the money arrived — it is credited."""
    from datetime import timedelta

    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-late")
    topup.expires_at = clock.now() - timedelta(minutes=1)
    await db_session.commit()
    assert (await _perform(db_session, "pt-late"))["state"] == 2
    assert await user_balance(db_session, topup.user_id) == AMOUNT


async def test_perform_unknown_is_31003(db_session: AsyncSession) -> None:
    assert (await _code(_perform(db_session, "nope"))).code == -31003


async def test_perform_on_cancelled_is_31008(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-perform-cancelled")
    await _cancel(db_session, "pt-perform-cancelled")
    err = await _code(_perform(db_session, "pt-perform-cancelled"))
    assert (err.code, err.persist) == (-31008, False)


async def test_perform_after_paid_elsewhere_is_31008(db_session: AsyncSession) -> None:
    """The top-up was credited through another kassa while Payme held it: this charge is a
    second one. −31008, and the transaction is cancelled (−1, reason 3) and kept."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-elsewhere")
    await _settle_elsewhere(db_session, topup)

    err = await _code(_perform(db_session, "pt-elsewhere"))
    assert (err.code, err.persist) == (-31008, True)
    await db_session.commit()  # what the route does for a persisting refusal
    row = await _txn(db_session, "pt-elsewhere")
    assert (row.state, row.reason, row.perform_time) == (-1, 3, 0)
    assert row.cancel_time > 0
    assert (await _payment(db_session, row.payment_id)).status == "cancelled"
    assert await user_balance(db_session, topup.user_id) == AMOUNT
    check = await payme_svc.check_transaction(db_session, payme_id="pt-elsewhere")
    assert (check["state"], check["reason"]) == (-1, 3)


async def test_perform_on_an_attempt_a_sibling_settled_is_31008(
    db_session: AsyncSession,
) -> None:
    """Two Payme rows sharing one attempt (not reachable through Create, which answers
    −31099): the second perform must not answer success for a settled attempt."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-sib-a")
    row_a = await _txn(db_session, "pt-sib-a")
    db_session.add(
        PaymeTransaction(
            payme_id="pt-sib-b",
            payment_id=row_a.payment_id,
            account=topup.number,
            amount_tiyin=TIYIN,
            state=1,
            create_time=TIME + 1,
        )
    )
    await db_session.commit()
    await _perform(db_session, "pt-sib-a")
    err = await _code(_perform(db_session, "pt-sib-b"))
    assert (err.code, err.persist) == (-31008, True)
    await db_session.commit()
    assert (await _txn(db_session, "pt-sib-b")).state == -1
    assert (await _payment(db_session, row_a.payment_id)).status == "succeeded"
    assert await user_balance(db_session, topup.user_id) == AMOUNT


# ---------- CancelTransaction ----------


async def test_cancel_created_goes_to_minus_1_and_releases_the_attempt(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    created = await _create(db_session, topup, "pt-cancel-1")
    result = await _cancel(db_session, "pt-cancel-1", reason=2)
    row = await _txn(db_session, "pt-cancel-1")
    assert result == {
        "transaction": created["transaction"],
        "cancel_time": row.cancel_time,
        "state": -1,
    }
    assert (row.state, row.reason) == (-1, 2)
    assert row.cancel_time > 0
    assert (await _payment(db_session, row.payment_id)).status == "cancelled"
    await db_session.refresh(topup)
    assert topup.status == "pending"


async def test_cancel_performed_unspent_reverses_to_minus_2(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-cancel-2")
    await _perform(db_session, "pt-cancel-2")
    result = await _cancel(db_session, "pt-cancel-2", reason=5)
    assert result["state"] == -2
    row = await _txn(db_session, "pt-cancel-2")
    assert (row.state, row.reason) == (-2, 5)
    payment = await _payment(db_session, row.payment_id)
    assert payment.status == "refunded"
    assert payment.extra_metadata["reverse_event_id"] == "payme:pt-cancel-2"
    await db_session.refresh(topup)
    assert topup.status == "reversed"
    assert await user_balance(db_session, topup.user_id) == 0


async def test_cancel_performed_spent_topup_is_31007(db_session: AsyncSession) -> None:
    """Ruling R7: the money already left the balance — Payme's refund is refused."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-spent")
    await _perform(db_session, "pt-spent")
    await _spend(db_session, topup, Decimal(10000))
    user_id = topup.user_id

    err = await _code(_cancel(db_session, "pt-spent", reason=5))
    assert (err.code, err.persist) == (-31007, False)
    await db_session.rollback()
    row = await _txn(db_session, "pt-spent")
    assert (row.state, row.reason, row.cancel_time) == (2, None, 0)
    assert (await _payment(db_session, row.payment_id)).status == "succeeded"
    assert await user_balance(db_session, user_id) == Decimal(40000)


async def test_cancel_replay_echoes_the_stored_result(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-cancel-replay")
    await _perform(db_session, "pt-cancel-replay")
    first = await _cancel(db_session, "pt-cancel-replay", reason=5)
    second = await _cancel(db_session, "pt-cancel-replay", reason=1)
    assert first == second
    assert (await _txn(db_session, "pt-cancel-replay")).reason == 5
    assert await user_balance(db_session, topup.user_id) == 0


async def test_cancel_unknown_is_31003(db_session: AsyncSession) -> None:
    assert (await _code(_cancel(db_session, "nope"))).code == -31003


async def test_cancel_with_an_active_sibling_keeps_the_attempt_payable(
    db_session: AsyncSession,
) -> None:
    """Ruling 4: a cancel releases a shared attempt only when no other state-1 row holds it."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-share-a")
    row_a = await _txn(db_session, "pt-share-a")
    db_session.add(
        PaymeTransaction(
            payme_id="pt-share-b",
            payment_id=row_a.payment_id,
            account=topup.number,
            amount_tiyin=TIYIN,
            state=1,
            create_time=TIME + 1,
        )
    )
    await db_session.commit()
    await _cancel(db_session, "pt-share-a")
    assert (await _payment(db_session, row_a.payment_id)).status == "pending"
    assert (await _perform(db_session, "pt-share-b"))["state"] == 2
    assert await user_balance(db_session, topup.user_id) == AMOUNT


# ---------- CheckTransaction ----------


async def test_check_transaction_shape(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    created = await _create(db_session, topup, "pt-check")
    result = await payme_svc.check_transaction(db_session, payme_id="pt-check")
    assert result == {
        "create_time": TIME,
        "perform_time": 0,
        "cancel_time": 0,
        "transaction": created["transaction"],
        "state": 1,
        "reason": None,
    }


async def test_check_transaction_unknown_is_31003(db_session: AsyncSession) -> None:
    assert (await _code(payme_svc.check_transaction(db_session, payme_id="nope"))).code == -31003


# ---------- GetStatement ----------


async def test_get_statement_window_ascending(db_session: AsyncSession) -> None:
    topups = [await make_topup(db_session) for _ in range(4)]
    for payme_id, topup, t in (
        ("pt-stmt-late", topups[0], 300),
        ("pt-stmt-early", topups[1], 100),
        ("pt-stmt-mid-b", topups[2], 250),
        ("pt-stmt-mid-a", topups[3], 200),
    ):
        await _create(db_session, topup, payme_id, time=t)

    result = await payme_svc.get_statement(db_session, from_ms=150, to_ms=250)
    assert [tx["id"] for tx in result["transactions"]] == ["pt-stmt-mid-a", "pt-stmt-mid-b"]
    row = result["transactions"][0]
    stored = await _txn(db_session, "pt-stmt-mid-a")
    assert row == {
        "id": "pt-stmt-mid-a",
        "time": 200,
        "amount": TIYIN,
        "account": {"order": topups[3].number},
        "create_time": 200,
        "perform_time": 0,
        "cancel_time": 0,
        "transaction": stored.id,
        "state": 1,
        "reason": None,
        "receivers": [],
    }


async def test_get_statement_empty_window(db_session: AsyncSession) -> None:
    assert await payme_svc.get_statement(db_session, from_ms=1, to_ms=2) == {"transactions": []}


# ---------- SetFiscalData ----------


async def test_set_fiscal_data_stores_by_type(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "pt-fiscal")
    receipt = {"receipt_id": 1, "status_code": 0, "fiscal_sign": "123456"}
    for kind in ("PERFORM", "CANCEL"):
        assert await payme_svc.set_fiscal_data(
            db_session, payme_id="pt-fiscal", type_=kind, fiscal_data=receipt
        ) == {"success": True}
        await db_session.commit()
    assert (await _txn(db_session, "pt-fiscal")).fiscal_data == {
        "PERFORM": receipt,
        "CANCEL": receipt,
    }


async def test_set_fiscal_data_unknown_is_32001(db_session: AsyncSession) -> None:
    err = await _code(
        payme_svc.set_fiscal_data(db_session, payme_id="nope", type_="PERFORM", fiscal_data={})
    )
    assert err.code == -32001


# ---------- lock order: top-up → Payme row → payment ----------


@pytest.mark.parametrize("call", ["create_replay", "perform", "cancel", "set_fiscal_data"])
async def test_handlers_lock_the_topup_before_the_payme_row(
    db_engine: AsyncEngine, call: str
) -> None:
    """A holder takes the top-up, the handler starts, then the holder takes the Payme row
    (what the timeout sweep does). A handler that locked the row before the top-up would
    deadlock here; with the global order it just waits, then finishes."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        topup = await make_topup(setup)
        await _create(setup, topup, "pt-lock")

    async def handler() -> None:
        async with factory() as db:
            if call == "create_replay":
                await payme_svc.create_transaction(
                    db, payme_id="pt-lock", time=TIME, amount=TIYIN, account={"order": topup.number}
                )
            elif call == "perform":
                await payme_svc.perform_transaction(db, payme_id="pt-lock")
            elif call == "cancel":
                await payme_svc.cancel_transaction(db, payme_id="pt-lock", reason=1)
            else:
                await payme_svc.set_fiscal_data(
                    db, payme_id="pt-lock", type_="PERFORM", fiscal_data={"a": 1}
                )
            await db.commit()

    async with factory() as holder:
        await resolve(holder, topup.number, lock=True)
        task = asyncio.create_task(handler())
        await asyncio.sleep(0.3)
        assert not task.done()  # waiting on the top-up, holding nothing else
        await holder.execute(
            select(PaymeTransaction.id)
            .where(PaymeTransaction.payme_id == "pt-lock")
            .with_for_update()
        )
        await holder.commit()
    await asyncio.wait_for(task, timeout=10)
