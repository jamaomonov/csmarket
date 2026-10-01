"""Spec §14: hypothesis on the ledger — every posting keeps SUM(D) == SUM(C), and purchases
and refunds of orders (rulings R8, R9) never drive a balance below zero."""

from __future__ import annotations

from decimal import Decimal

from csmarket.modules.users.api import upsert_user_by_steam
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    Leg,
    credit_order_refund,
    credit_topup,
    debit_purchase,
    ensure_account,
    post,
    user_account,
    user_balance,
)
from csmarket.modules.wallet.models import WalletPosting
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

amounts = st.lists(st.integers(min_value=1, max_value=10_000_000), min_size=1, max_size=20)


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(amounts=amounts)
async def test_debits_always_equal_credits(db_session: AsyncSession, amounts: list[int]) -> None:
    uid = (
        await upsert_user_by_steam(
            db_session, steam_id="76561198000000199", display_name=None, avatar_url=None
        )
    ).id
    w = await user_account(db_session, uid)
    c = await ensure_account(
        db_session, owner_type="provider", owner_id="uzum", kind="provider_clearing"
    )
    try:
        for i, a in enumerate(amounts):
            await post(
                db_session,
                kind="topup",
                legs=[Leg(w.id, "D", Decimal(a)), Leg(c.id, "C", Decimal(a))],
                idempotency_key=f"p{len(amounts)}:{i}:{a}",
            )
        await db_session.flush()
        d = await db_session.scalar(
            select(func.coalesce(func.sum(WalletPosting.amount), 0)).where(
                WalletPosting.direction == "D"
            )
        )
        c_sum = await db_session.scalar(
            select(func.coalesce(func.sum(WalletPosting.amount), 0)).where(
                WalletPosting.direction == "C"
            )
        )
        assert d == c_sum
        assert await user_balance(db_session, uid) == Decimal(sum(amounts))
    finally:
        await db_session.rollback()


#: One ledger event: a top-up, a purchase from the balance, or a refund of an earlier order.
_events = st.lists(
    st.one_of(
        st.tuples(st.just("topup"), st.integers(min_value=1, max_value=2_000_000)),
        st.tuples(st.just("buy"), st.integers(min_value=1, max_value=2_000_000)),
        st.tuples(st.just("refund"), st.integers(min_value=0, max_value=30)),
        st.tuples(st.just("kassa_refund"), st.integers(min_value=1, max_value=2_000_000)),
    ),
    min_size=1,
    max_size=25,
)


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(events=_events)
async def test_purchases_and_refunds_stay_balanced_and_never_overdraw(
    db_session: AsyncSession, events: list[tuple[str, int]]
) -> None:
    """Rulings R8/R9: a purchase is booked once and only when covered, a refund once; every
    posting keeps SUM(D) == SUM(C) and the balance never goes below zero."""
    uid = (
        await upsert_user_by_steam(
            db_session, steam_id="76561198000000198", display_name=None, avatar_url=None
        )
    ).id
    expected = Decimal(0)
    bought: list[tuple[str, Decimal]] = []
    refunded: set[str] = set()
    try:
        for i, (op, n) in enumerate(events):
            if op == "topup":
                await credit_topup(
                    db_session, user_id=uid, topup_id=f"t{i}", amount=Decimal(n), provider="uzum"
                )
                expected += n
            elif op == "buy":
                order_id = f"o{i}"
                try:
                    async with db_session.begin_nested():
                        await debit_purchase(
                            db_session, user_id=uid, order_id=order_id, amount=Decimal(n)
                        )
                except InsufficientBalanceError:
                    assert expected < n
                else:
                    assert expected >= n
                    expected -= n
                    bought.append((order_id, Decimal(n)))
                    # A replay books nothing more, whatever the balance is now.
                    await debit_purchase(
                        db_session, user_id=uid, order_id=order_id, amount=Decimal(n)
                    )
            elif op == "refund" and bought:
                order_id, amount = bought[n % len(bought)]
                await credit_order_refund(
                    db_session, user_id=uid, order_id=order_id, amount=amount, paid_with="wallet"
                )
                if order_id not in refunded:
                    refunded.add(order_id)
                    expected += amount
            elif op == "kassa_refund":
                await credit_order_refund(
                    db_session, user_id=uid, order_id=f"k{i}", amount=Decimal(n), paid_with="payme"
                )
                expected += n
            assert await user_balance(db_session, uid) == expected >= 0
        await db_session.flush()
        sums = {
            d: await db_session.scalar(
                select(func.coalesce(func.sum(WalletPosting.amount), 0)).where(
                    WalletPosting.direction == d
                )
            )
            for d in ("D", "C")
        }
        assert sums["D"] == sums["C"]
    finally:
        await db_session.rollback()
