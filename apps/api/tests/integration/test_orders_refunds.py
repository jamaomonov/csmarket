"""``orders.refunds``: an order is refunded to the balance exactly once (rulings R3, R9),
never while its skin is in flight, and an admin refunds only an attention order whose
Waxpeer side an operator checked."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core.errors import AppError, ConflictError, NotFoundError
from csmarket.core.ids import new_id
from csmarket.modules.orders.api import (
    InvalidOrderTransitionError,
    Order,
    SkinTrade,
    admin_refund,
    in_flight,
    refund_to_balance,
)
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import credit_topup, debit_purchase, user_balance
from csmarket.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction
from httpx import AsyncClient
from prometheus_client import REGISTRY
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.orders_factory import make_order, make_trade
from tests.integration.payments_factory import make_user

PRICE = Decimal(171_800)
Headers = Callable[[], Awaitable[dict[str, str]]]


# --- helpers -------------------------------------------------------------------------------


async def _wallet_paid(
    db: AsyncSession, *, status: str = "buying", user: User | None = None
) -> Order:
    """A committed order paid from the balance (purchase booked) in ``status``."""
    owner = user or await make_user(db)
    await credit_topup(
        db, user_id=owner.id, topup_id=new_id(), amount=Decimal(500_000), provider="mock"
    )
    order = await make_order(
        db, user=owner, status=status, paid_with="wallet", paid_at=clock.now(), price_uzs=PRICE
    )
    await debit_purchase(db, user_id=owner.id, order_id=order.id, amount=PRICE)
    await db.commit()
    return order


async def _kassa_paid(
    db: AsyncSession, *, provider: str = "payme", status: str = "buying"
) -> Order:
    return await make_order(
        db, status=status, paid_with=provider, paid_at=clock.now(), price_uzs=PRICE
    )


async def _locked(db: AsyncSession, order_id: str) -> Order:
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _refunds(db: AsyncSession, order_id: str) -> list[WalletTransaction]:
    stmt = select(WalletTransaction).where(
        WalletTransaction.kind == "refund", WalletTransaction.reference_id == order_id
    )
    return list((await db.execute(stmt)).scalars())


async def _legs(db: AsyncSession, txn: WalletTransaction) -> set[tuple[str, str, str, Decimal]]:
    rows = await db.execute(
        select(
            WalletAccount.kind,
            WalletAccount.owner_id,
            WalletPosting.direction,
            WalletPosting.amount,
        )
        .join(WalletAccount, WalletAccount.id == WalletPosting.account_id)
        .where(WalletPosting.transaction_id == txn.id)
    )
    return {(kind, owner, d, Decimal(a)) for kind, owner, d, a in rows.all()}


async def _ledger_rows(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(WalletTransaction)) or 0)


def _refunds_metric(reason: str) -> float:
    value = REGISTRY.get_sample_value("csmarket_order_refunds_total", {"reason": reason})
    return value or 0.0


async def _code(call: Awaitable[object]) -> tuple[int, str | None]:
    with pytest.raises(AppError) as exc:
        await call
    return exc.value.status_code, exc.value.extra.get("code")


# --- refund_to_balance ---------------------------------------------------------------------


async def test_refund_twice_credits_once(db_session: AsyncSession) -> None:
    order = await _wallet_paid(db_session)
    before = _refunds_metric("sold_out")
    locked = await _locked(db_session, order.id)
    first = await refund_to_balance(
        db_session, order=locked, to_status="failed", reason="sold_out", actor="orders"
    )
    second = await refund_to_balance(
        db_session, order=locked, to_status="failed", reason="sold_out", actor="orders"
    )
    await db_session.commit()
    assert (first, second) == (True, False)
    assert len(await _refunds(db_session, order.id)) == 1
    assert await user_balance(db_session, order.user_id) == Decimal(500_000)
    assert _refunds_metric("sold_out") == before + 1
    row = await _locked(db_session, order.id)
    assert (row.status, row.refunded_to, row.failure_reason) == ("failed", "balance", "sold_out")
    assert row.refunded_at is not None
    assert row.failed_at is not None


async def test_a_refunded_order_is_never_refunded_again_from_another_session(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """Two sessions lock the order in turn: the second sees ``refunded_at`` and books
    nothing."""
    order = await _wallet_paid(db_session)
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    barrier = asyncio.Barrier(2)

    async def _one() -> bool:
        async with factory() as db:
            await barrier.wait()
            locked = await _locked(db, order.id)
            done = await refund_to_balance(
                db, order=locked, to_status="failed", reason="sold_out", actor="orders"
            )
            await db.commit()
            return done

    results = await asyncio.wait_for(asyncio.gather(_one(), _one()), timeout=15)
    assert sorted(results) == [False, True]
    assert len(await _refunds(db_session, order.id)) == 1
    assert await user_balance(db_session, order.user_id) == Decimal(500_000)


async def test_a_balance_paid_refund_undoes_the_purchase(db_session: AsyncSession) -> None:
    order = await _wallet_paid(db_session)
    locked = await _locked(db_session, order.id)
    await refund_to_balance(
        db_session, order=locked, to_status="failed", reason="sold_out", actor="orders"
    )
    await db_session.commit()
    [txn] = await _refunds(db_session, order.id)
    assert await _legs(db_session, txn) == {
        ("user_wallet", order.user_id, "D", PRICE),
        ("house_payments_received", "house", "C", PRICE),
    }
    assert (txn.actor, txn.reference_type, txn.idempotency_key) == (
        "orders",
        "order",
        f"refund:order:{order.id}",
    )


@pytest.mark.parametrize("provider", ["click", "payme", "uzum", "mock"])
async def test_a_kassa_paid_refund_turns_the_kassa_money_into_balance(
    db_session: AsyncSession, provider: str
) -> None:
    order = await _kassa_paid(db_session, provider=provider)
    locked = await _locked(db_session, order.id)
    assert await refund_to_balance(
        db_session, order=locked, to_status="failed", reason="waxpeer_low_balance", actor="orders"
    )
    await db_session.commit()
    [txn] = await _refunds(db_session, order.id)
    assert await _legs(db_session, txn) == {
        ("user_wallet", order.user_id, "D", PRICE),
        ("provider_clearing", provider, "C", PRICE),
    }
    assert await user_balance(db_session, order.user_id) == PRICE


async def test_a_declined_trade_is_returned_with_the_refund(db_session: AsyncSession) -> None:
    order = await _kassa_paid(db_session, status="trade_sent")
    locked = await _locked(db_session, order.id)
    assert await refund_to_balance(
        db_session, order=locked, to_status="returned", reason="not_accepted", actor="orders"
    )
    await db_session.commit()
    row = await _locked(db_session, order.id)
    assert (row.status, row.failure_reason, row.refunded_to) == (
        "returned",
        "not_accepted",
        "balance",
    )
    assert row.failed_at is not None


async def test_a_refund_off_the_fsm_writes_nothing(db_session: AsyncSession) -> None:
    order = await _wallet_paid(db_session, status="delivered")
    order_id = order.id
    rows = await _ledger_rows(db_session)
    locked = await _locked(db_session, order_id)
    with pytest.raises(InvalidOrderTransitionError):
        await refund_to_balance(
            db_session, order=locked, to_status="returned", reason="not_accepted", actor="orders"
        )
    await db_session.flush()
    assert await _refunds(db_session, order_id) == []
    await db_session.rollback()
    assert await _ledger_rows(db_session) == rows
    row = await _locked(db_session, order_id)
    assert (row.status, row.refunded_at) == ("delivered", None)


async def test_an_unpaid_order_is_never_refunded(db_session: AsyncSession) -> None:
    order = await make_order(db_session, status="buying")
    locked = await _locked(db_session, order.id)
    assert await _code(
        refund_to_balance(
            db_session, order=locked, to_status="failed", reason="sold_out", actor="orders"
        )
    ) == (409, "order_not_paid")
    assert locked.status == "buying"


async def test_a_caller_bug_is_refused(db_session: AsyncSession) -> None:
    order = await _kassa_paid(db_session)
    locked = await _locked(db_session, order.id)
    with pytest.raises(ValueError, match="to_status"):
        await refund_to_balance(
            db_session,
            order=locked,
            to_status="delivered",  # type: ignore[arg-type]  # the bug under test
            reason="sold_out",
            actor="orders",
        )
    with pytest.raises(ValueError, match="reason"):
        await refund_to_balance(
            db_session, order=locked, to_status="failed", reason="oops", actor="orders"
        )
    assert (locked.status, locked.refunded_at) == ("buying", None)
    assert await _refunds(db_session, order.id) == []


# --- in_flight -----------------------------------------------------------------------------


def _bare(status: str) -> Order:
    return Order(status=status)


def _trade(reason: str | None, *, resolved: bool = False) -> SkinTrade:
    return SkinTrade(attention_reason=reason, resolved_at=clock.now() if resolved else None)


@pytest.mark.parametrize("status", ["paid", "buying", "trade_sent"])
def test_a_paid_unsettled_order_is_in_flight(status: str) -> None:
    assert in_flight(_bare(status), None)
    assert in_flight(_bare(status), _trade(None))
    assert in_flight(_bare(status), _trade("buy_unconfirmed", resolved=True))


@pytest.mark.parametrize("status", ["pending", "cancelled", "failed", "returned", "delivered"])
def test_a_settled_order_is_not_in_flight(status: str) -> None:
    assert not in_flight(_bare(status), None)
    assert not in_flight(_bare(status), _trade(None))
    assert not in_flight(_bare(status), _trade("rolled_back", resolved=True))


def test_a_delivered_order_under_attention_is_in_flight() -> None:
    assert in_flight(_bare("delivered"), _trade("rolled_back"))
    assert in_flight(_bare("delivered"), _trade("audit_divergence"))


# --- admin_refund --------------------------------------------------------------------------


async def _attention(
    db: AsyncSession, *, reason: str = "buy_unconfirmed", resolved: bool, status: str = "buying"
) -> Order:
    order = await _wallet_paid(db, status=status)
    await make_trade(
        db,
        order,
        attention_reason=reason,
        resolved_at=clock.now() - timedelta(minutes=1) if resolved else None,
        resolved_by="admin:someone" if resolved else None,
    )
    return order


async def test_refund_refused_while_in_flight(db_session: AsyncSession) -> None:
    admin = new_id()
    unresolved = await _attention(db_session, resolved=False)
    sent = await _wallet_paid(db_session, status="trade_sent")
    await make_trade(db_session, sent)
    rolled_back = await _attention(
        db_session, reason="rolled_back", resolved=False, status="delivered"
    )
    no_trade = await _wallet_paid(db_session, status="buying")
    paid = await _wallet_paid(db_session, status="paid")
    rows = await _ledger_rows(db_session)
    unresolved_id = unresolved.id
    numbers = [o.number for o in (unresolved, sent, rolled_back, no_trade, paid)]
    for number in numbers:
        assert await _code(admin_refund(db_session, number=number, admin_id=admin)) == (
            409,
            "order_in_flight",
        ), number
        await db_session.rollback()
    assert await _ledger_rows(db_session) == rows
    row = await _locked(db_session, unresolved_id)
    assert (row.status, row.refunded_at) == ("buying", None)


@pytest.mark.parametrize("reason", ["rolled_back", "audit_divergence"])
async def test_a_resolved_buying_order_needs_a_nothing_bought_reason(
    db_session: AsyncSession, reason: str
) -> None:
    order = await _attention(db_session, reason=reason, resolved=True)
    assert await _code(admin_refund(db_session, number=order.number, admin_id=new_id())) == (
        409,
        "order_in_flight",
    )


@pytest.mark.parametrize("reason", ["buy_unconfirmed", "ambiguous_trade", "waxpeer_forbidden"])
async def test_admin_refund_after_resolve_credits_the_balance(
    db_session: AsyncSession, reason: str
) -> None:
    order = await _attention(db_session, reason=reason, resolved=True)
    admin = new_id()
    before = _refunds_metric("admin")
    refunded = await admin_refund(db_session, number=order.number, admin_id=admin)
    await db_session.commit()
    assert refunded.id == order.id
    assert (refunded.status, refunded.failure_reason, refunded.refunded_to) == (
        "failed",
        "admin",
        "balance",
    )
    [txn] = await _refunds(db_session, order.id)
    assert txn.actor == f"admin:{admin}"
    assert await user_balance(db_session, order.user_id) == Decimal(500_000)
    assert _refunds_metric("admin") == before + 1


async def test_an_already_refunded_order_is_409(db_session: AsyncSession) -> None:
    order = await _attention(db_session, resolved=True)
    await admin_refund(db_session, number=order.number, admin_id=new_id())
    await db_session.commit()
    assert await _code(admin_refund(db_session, number=order.number, admin_id=new_id())) == (
        409,
        "already_refunded",
    )
    assert len(await _refunds(db_session, order.id)) == 1


async def test_a_settled_order_is_not_refundable(db_session: AsyncSession) -> None:
    pending = await make_order(db_session)
    cancelled = await make_order(db_session, status="cancelled")
    delivered = await _wallet_paid(db_session, status="delivered")
    await make_trade(db_session, delivered)
    resolved_rollback = await _attention(
        db_session, reason="rolled_back", resolved=True, status="delivered"
    )
    numbers = [o.number for o in (pending, cancelled, delivered, resolved_rollback)]
    for number in numbers:
        assert await _code(admin_refund(db_session, number=number, admin_id=new_id())) == (
            409,
            "order_not_refundable",
        ), number
        await db_session.rollback()


@pytest.mark.parametrize("number", ["ZZZZZZZZ", "bad", "T1234567"])
async def test_an_unknown_order_is_404(db_session: AsyncSession, number: str) -> None:
    with pytest.raises(NotFoundError):
        await admin_refund(db_session, number=number, admin_id=new_id())


async def test_admin_refund_raises_conflict_types(db_session: AsyncSession) -> None:
    order = await _attention(db_session, resolved=False)
    with pytest.raises(ConflictError):
        await admin_refund(db_session, number=order.number, admin_id=new_id())


# --- the customer's entries ----------------------------------------------------------------


async def test_the_refund_entry_carries_the_order_number(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    buyer = await db_session.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert buyer is not None
    order = await _wallet_paid(db_session, user=buyer)
    locked = await _locked(db_session, order.id)
    await refund_to_balance(
        db_session, order=locked, to_status="failed", reason="sold_out", actor="orders"
    )
    await db_session.commit()
    body = (await integration_client.get("/api/v1/wallet/entries", headers=h)).json()
    lines = {e["kind"]: e for e in body["items"]}
    assert (lines["refund"]["amount_uzs"], lines["refund"]["reference_number"]) == (
        f"+{PRICE}",
        order.number,
    )
    assert (lines["purchase"]["amount_uzs"], lines["purchase"]["reference_number"]) == (
        f"-{PRICE}",
        order.number,
    )
    assert lines["topup"]["reference_number"] is None  # a ledger-only top-up has no row
