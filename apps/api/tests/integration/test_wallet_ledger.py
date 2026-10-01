"""The wallet ledger: postings, replay by key, refused legs, balances (spec §5, R1)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal

import pytest
from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.modules.users.api import User, upsert_user_by_steam
from csmarket.modules.wallet.api import (
    Leg,
    Reference,
    balance,
    ensure_account,
    post,
    user_account,
    user_balance,
)
from csmarket.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def _user(db: AsyncSession, sid: str = "76561198000000101") -> str:
    return (await upsert_user_by_steam(db, steam_id=sid, display_name=None, avatar_url=None)).id


async def test_post_moves_money_and_balances_follow_normal_side(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    wallet = await user_account(db_session, uid)
    clearing = await ensure_account(
        db_session, owner_type="provider", owner_id="payme", kind="provider_clearing"
    )
    await post(
        db_session,
        kind="topup",
        legs=[Leg(wallet.id, "D", Decimal(50000)), Leg(clearing.id, "C", Decimal(50000))],
        idempotency_key="t1",
    )
    await db_session.commit()
    assert await balance(db_session, wallet.id) == Decimal(50000)
    assert await balance(db_session, clearing.id) == Decimal(50000)
    assert await user_balance(db_session, uid) == Decimal(50000)


async def test_replay_by_key_posts_once(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    w = await user_account(db_session, uid)
    c = await ensure_account(
        db_session, owner_type="provider", owner_id="click", kind="provider_clearing"
    )
    legs = [Leg(w.id, "D", Decimal(1000)), Leg(c.id, "C", Decimal(1000))]
    a = await post(db_session, kind="topup", legs=legs, idempotency_key="same")
    b = await post(db_session, kind="topup", legs=legs, idempotency_key="same")
    await db_session.commit()
    assert a.id == b.id
    assert await user_balance(db_session, uid) == Decimal(1000)


LegsFn = Callable[[str, str], list[Leg]]


@pytest.mark.parametrize(
    "legs",
    [
        lambda w, c: [Leg(w, "D", Decimal(100))],
        lambda w, c: [Leg(w, "D", Decimal(100)), Leg(c, "C", Decimal(99))],
        lambda w, c: [Leg(w, "D", Decimal("100.5")), Leg(c, "C", Decimal("100.5"))],
        lambda w, c: [Leg(w, "D", Decimal(0)), Leg(c, "C", Decimal(0))],
        lambda w, c: [Leg(w, "D", Decimal(-5)), Leg(c, "C", Decimal(-5))],
        lambda w, c: [Leg(w, "X", Decimal(5)), Leg(c, "C", Decimal(5))],  # type: ignore[arg-type]
        lambda w, c: [Leg(w, "D", Decimal(10**14)), Leg(c, "C", Decimal(10**14))],
        lambda w, c: [Leg(w, "D", Decimal("NaN")), Leg(c, "C", Decimal("NaN"))],
    ],
    ids=[
        "one-leg",
        "unbalanced",
        "fractional",
        "zero",
        "negative",
        "bad-direction",
        "too-large",
        "nan",
    ],
)
async def test_bad_legs_are_refused(db_session: AsyncSession, legs: LegsFn) -> None:
    uid = await _user(db_session)
    w = await user_account(db_session, uid)
    c = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_adjustments"
    )
    with pytest.raises(ValidationError):
        await post(db_session, kind="admin_adjust", legs=legs(w.id, c.id), idempotency_key="bad")
    assert await db_session.scalar(select(func.count()).select_from(WalletTransaction)) == 0


async def test_no_account_means_zero(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    assert await user_balance(db_session, uid) == Decimal(0)
    # Reading a balance never creates an account.
    assert await db_session.scalar(select(func.count()).select_from(WalletAccount)) == 0


async def test_unknown_kinds_are_refused(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    w = await user_account(db_session, uid)
    c = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_adjustments"
    )
    with pytest.raises(ValidationError):
        await ensure_account(db_session, owner_type="user", owner_id=uid, kind="user_cashback")
    with pytest.raises(ValidationError):
        await ensure_account(db_session, owner_type="partner", owner_id=uid, kind="user_wallet")
    with pytest.raises(ValidationError):
        await post(
            db_session,
            kind="promo",
            legs=[Leg(w.id, "D", Decimal(1)), Leg(c.id, "C", Decimal(1))],
            idempotency_key="k",
        )


async def test_missing_account_is_not_found(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    w = await user_account(db_session, uid)
    with pytest.raises(NotFoundError):
        await post(
            db_session,
            kind="topup",
            legs=[
                Leg(w.id, "D", Decimal(5)),
                Leg("00000000-0000-7000-8000-000000000000", "C", Decimal(5)),
            ],
            idempotency_key="missing",
        )
    with pytest.raises(NotFoundError):
        await balance(db_session, "00000000-0000-7000-8000-000000000000")


async def test_frozen_account_refuses_postings(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    w = await user_account(db_session, uid)
    c = await ensure_account(
        db_session, owner_type="provider", owner_id="click", kind="provider_clearing"
    )
    w.status = "frozen"
    await db_session.flush()
    with pytest.raises(ConflictError):
        await post(
            db_session,
            kind="topup",
            legs=[Leg(w.id, "D", Decimal(5)), Leg(c.id, "C", Decimal(5))],
            idempotency_key="frozen",
        )


async def test_post_records_reference_actor_metadata_and_legs(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    w = await user_account(db_session, uid)
    c = await ensure_account(
        db_session, owner_type="provider", owner_id="uzum", kind="provider_clearing"
    )
    txn = await post(
        db_session,
        kind="topup",
        legs=[Leg(w.id, "D", Decimal(7000)), Leg(c.id, "C", Decimal(7000))],
        idempotency_key="topup:abc",
        reference=Reference("topup", "abc"),
        actor="click",
        metadata={"number": "T1"},
    )
    await db_session.commit()
    row = await db_session.get(WalletTransaction, txn.id)
    assert row is not None
    assert (row.kind, row.reference_type, row.reference_id, row.actor) == (
        "topup",
        "topup",
        "abc",
        "click",
    )
    assert row.extra_metadata == {"number": "T1"}
    legs = (
        await db_session.scalars(
            select(WalletPosting).where(WalletPosting.transaction_id == txn.id)
        )
    ).all()
    assert sorted((p.direction, p.amount) for p in legs) == [
        ("C", Decimal(7000)),
        ("D", Decimal(7000)),
    ]


async def test_debit_on_a_debit_normal_account_lowers_it(db_session: AsyncSession) -> None:
    uid = await _user(db_session)
    w = await user_account(db_session, uid)
    c = await ensure_account(
        db_session, owner_type="provider", owner_id="payme", kind="provider_clearing"
    )
    h = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_adjustments"
    )
    await post(
        db_session,
        kind="topup",
        legs=[Leg(w.id, "D", Decimal(5000)), Leg(c.id, "C", Decimal(5000))],
        idempotency_key="in",
    )
    await post(
        db_session,
        kind="admin_adjust",
        legs=[Leg(h.id, "D", Decimal(1500)), Leg(w.id, "C", Decimal(1500))],
        idempotency_key="out",
    )
    assert await user_balance(db_session, uid) == Decimal(3500)
    assert await balance(db_session, h.id) == Decimal(1500)


async def test_ensure_account_is_idempotent_and_user_account_locks(
    db_session: AsyncSession,
) -> None:
    uid = await _user(db_session)
    a = await user_account(db_session, uid)
    b = await user_account(db_session, uid, lock=True)
    c = await ensure_account(db_session, owner_type="user", owner_id=uid, kind="user_wallet")
    assert a.id == b.id == c.id
    assert (a.owner_type, a.kind, a.status) == ("user", "user_wallet", "active")


async def test_lost_account_race_keeps_the_callers_transaction(db_engine: AsyncEngine) -> None:
    """Two sessions create one account at once: the loser reuses the winner's row and the
    loser's own earlier work in the same transaction survives (SAVEPOINT, not ROLLBACK)."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as s1, factory() as s2:
        uid = await _user(s1)
        await s1.commit()
        other = await _user(s2, sid="76561198000000102")  # s2's pending work
        winner = await ensure_account(s1, owner_type="user", owner_id=uid, kind="user_wallet")
        loser = asyncio.create_task(
            ensure_account(s2, owner_type="user", owner_id=uid, kind="user_wallet")
        )
        await asyncio.sleep(0.3)  # s2's INSERT now waits on s1's uncommitted unique key
        await s1.commit()
        again = await loser
        await s2.commit()
        assert again.id == winner.id
        assert await user_balance(s2, other) == Decimal(0)
        assert await s2.scalar(select(func.count()).select_from(User).where(User.id == other)) == 1


async def test_lost_post_race_replays_the_winner(db_engine: AsyncEngine) -> None:
    """Two sessions post one key at once: one transaction, the loser gets the winner's."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as s1, factory() as s2:
        uid = await _user(s1)
        w = await user_account(s1, uid)
        c = await ensure_account(
            s1, owner_type="provider", owner_id="click", kind="provider_clearing"
        )
        await s1.commit()
        legs = [Leg(w.id, "D", Decimal(2500)), Leg(c.id, "C", Decimal(2500))]
        first = await post(s1, kind="topup", legs=legs, idempotency_key="topup:race")
        second = asyncio.create_task(
            post(s2, kind="topup", legs=legs, idempotency_key="topup:race")
        )
        await asyncio.sleep(0.3)
        await s1.commit()
        replay = await second
        await s2.commit()
        assert replay.id == first.id
        assert await user_balance(s2, uid) == Decimal(2500)
