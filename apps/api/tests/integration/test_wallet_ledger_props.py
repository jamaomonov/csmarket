"""Spec §14: hypothesis on the ledger — every posting keeps SUM(D) == SUM(C)."""

from __future__ import annotations

from decimal import Decimal

from csmarket.modules.users.api import upsert_user_by_steam
from csmarket.modules.wallet.api import Leg, ensure_account, post, user_account, user_balance
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
