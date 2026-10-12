# apps/api/tests/integration/test_sales_status.py
"""The status machine (spec 2026-10-08 §6): every transition, the credit once, reversals."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.realtime.api import CHANNEL
from csmarket.modules.sales.models import Sale
from csmarket.modules.sales.payouts import request_of
from csmarket.modules.sales.status import Outcome, apply_deposit, check_sale, close, lock_sale
from csmarket.modules.skinslink.api import Deposit, SkinslinkUnavailableError
from csmarket.modules.wallet.api import WalletTransaction, user_account, user_balance
from prometheus_client import REGISTRY
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.orders_factory import listen_channel
from tests.integration.sales_factory import make_request, make_sale

pytestmark = pytest.mark.asyncio


async def _apply(db: AsyncSession, sale: Sale, report: Deposit | None) -> Outcome:
    locked = await lock_sale(db, sale.id)
    assert locked is not None
    outcome = await apply_deposit(db, locked, report, at=now())
    await db.commit()
    return outcome


async def _fresh(db: AsyncSession, sale: Sale) -> Sale:
    row = await db.get(Sale, sale.id, populate_existing=True)
    assert row is not None
    return row


async def _letters(db: AsyncSession, sale: Sale) -> list[str]:
    rows = await db.scalars(
        select(EmailOutbox.kind).where(EmailOutbox.sale_id == sale.id).order_by("created_at")
    )
    return list(rows)


async def _credits(db: AsyncSession, sale: Sale) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(WalletTransaction)
            .where(WalletTransaction.reference_id == sale.id)
        )
        or 0
    )


async def test_an_active_deposit_offers_the_creating_sale(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="creating")
    report = deposit("active", amount_usd=Decimal("12.95"))
    assert await _apply(db_session, sale, report) == "offered"
    s = await _fresh(db_session, sale)
    assert (s.status, s.trade_id, s.trade_offer_id, s.bot_name) == (
        "offered",
        42,
        "6912345678",
        "Bot #3",
    )
    assert s.offer_expiry_at == datetime(2026, 10, 8, 12, 30, tzinfo=UTC)
    assert s.amount_usd == Decimal("12.95")
    assert await _apply(db_session, sale, deposit("pending")) == "unchanged"


async def test_new_and_pending_only_record_the_poll_on_a_creating_sale(
    db_session: AsyncSession,
) -> None:
    for status in ("new", "pending"):
        sale = await make_sale(db_session, status="creating")
        assert await _apply(db_session, sale, deposit(status)) == "unchanged"
        s = await _fresh(db_session, sale)
        assert (s.status, s.trade_id, s.bot_name) == ("creating", 42, "Bot #3")


async def test_hold_never_steps_back_to_offered(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold")
    assert await _apply(db_session, sale, deposit("active")) == "unchanged"
    assert (await _fresh(db_session, sale)).status == "hold"


async def test_hold_stores_its_end_and_opens_a_waiting_card_request(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, payout_to="card", payout_uzs=Decimal(147_400))
    report = deposit("hold", hold_end_date="2026-10-15T10:00:00Z")
    assert await _apply(db_session, sale, report) == "hold"
    s = await _fresh(db_session, sale)
    assert s.hold_end_at == datetime(2026, 10, 15, 10, tzinfo=UTC)
    request = await request_of(db_session, sale.id)
    assert request is not None
    assert (request.status, request.amount_uzs, request.fee_uzs, request.to_pay_at) == (
        "waiting_hold",
        Decimal(147_400),
        Decimal(7_800),
        None,
    )
    assert await _letters(db_session, sale) == ["sale_hold"]


async def test_completed_twice_credits_the_balance_once(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold", payout_uzs=Decimal(158_300))
    assert await _apply(db_session, sale, deposit("completed")) == "credited"
    assert await _apply(db_session, sale, deposit("completed")) == "unchanged"
    s = await _fresh(db_session, sale)
    assert s.status == "credited"
    assert s.credited_at is not None
    assert await user_balance(db_session, sale.user_id) == Decimal(158_300)
    assert await _credits(db_session, sale) == 1
    assert await _letters(db_session, sale) == ["sale_paid"]


async def test_completed_makes_a_card_request_payable(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, payout_to="card", payout_uzs=Decimal(147_400))
    await _apply(db_session, sale, deposit("hold"))
    assert await _apply(db_session, sale, deposit("completed")) == "payout"
    request = await request_of(db_session, sale.id)
    assert request is not None
    assert request.status == "to_pay"
    assert request.to_pay_at is not None
    assert (await _fresh(db_session, sale)).status == "payout"
    assert await user_balance(db_session, sale.user_id) == 0


async def test_completed_without_a_hold_still_opens_a_payable_request(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, payout_to="card")
    assert await _apply(db_session, sale, deposit("completed")) == "payout"
    request = await request_of(db_session, sale.id)
    assert request is not None
    assert request.status == "to_pay"


async def test_failed_closes_and_cancels_the_request(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold", payout_to="card")
    await make_request(db_session, sale, status="waiting_hold")
    report = deposit("failed", fail_reason="canceled_by_user")
    assert await _apply(db_session, sale, report) == "closed"
    s = await _fresh(db_session, sale)
    assert (s.status, s.fail_reason) == ("closed", "canceled_by_user")
    request = await request_of(db_session, sale.id)
    assert request is not None
    assert request.status == "canceled"
    assert await _letters(db_session, sale) == ["sale_canceled"]


async def test_a_creating_sale_that_fails_closes_without_a_letter(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="creating")
    assert await _apply(db_session, sale, deposit("canceled")) == "closed"
    assert await _letters(db_session, sale) == []


async def test_reverted_out_of_hold_pays_nothing_and_cancels_the_request(
    db_session: AsyncSession,
) -> None:
    card_sale = await make_sale(db_session, status="hold", payout_to="card")
    await make_request(db_session, card_sale, status="waiting_hold")
    balance_sale = await make_sale(db_session, status="hold")
    for sale in (card_sale, balance_sale):
        report = deposit("reverted", fail_reason="user_reverted")
        assert await _apply(db_session, sale, report) == "reverted"
        assert (await _fresh(db_session, sale)).fail_reason == "user_reverted"
        assert await user_balance(db_session, sale.user_id) == 0
        assert await _credits(db_session, sale) == 0
    request = await request_of(db_session, card_sale.id)
    assert request is not None
    assert request.status == "canceled"


async def test_reverted_after_a_credit_opens_rolled_back_and_never_debits(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, status="hold", payout_uzs=Decimal(158_300))
    await _apply(db_session, sale, deposit("completed"))
    assert await _apply(db_session, sale, deposit("reverted")) == "attention"
    assert await _apply(db_session, sale, deposit("reverted")) == "unchanged"
    s = await _fresh(db_session, sale)
    assert (s.status, s.attention_reason) == ("credited", "rolled_back")
    assert await user_balance(db_session, sale.user_id) == Decimal(158_300)
    assert await _credits(db_session, sale) == 1


async def test_a_reverted_payout_still_to_pay_waits_for_the_admin(
    db_session: AsyncSession,
) -> None:
    """SB-3: the admin may be paying it right now; the request is never canceled under them."""
    sale = await make_sale(db_session, status="payout", payout_to="card")
    await make_request(db_session, sale, status="to_pay")
    assert await _apply(db_session, sale, deposit("reverted")) == "attention"
    request = await request_of(db_session, sale.id)
    assert request is not None
    assert request.status == "to_pay"
    s = await _fresh(db_session, sale)
    assert (s.status, s.attention_reason) == ("payout", "rolled_back")
    assert await _letters(db_session, sale) == []


async def test_a_reverted_payout_already_paid_waits_for_an_admin(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="payout", payout_to="card")
    await make_request(db_session, sale, status="paid")
    assert await _apply(db_session, sale, deposit("reverted")) == "attention"
    s = await _fresh(db_session, sale)
    assert (s.status, s.attention_reason) == ("payout", "rolled_back")


async def test_a_creating_sale_unknown_after_the_grace_closes(db_session: AsyncSession) -> None:
    young = await make_sale(db_session, status="creating")
    assert await _apply(db_session, young, None) == "unchanged"
    mid = await make_sale(db_session, status="creating", created_at=now() - timedelta(minutes=3))
    assert await _apply(db_session, mid, None) == "unchanged"  # SB-1: a slow Steam is slow
    old = await make_sale(db_session, status="creating", created_at=now() - timedelta(minutes=11))
    assert await _apply(db_session, old, None) == "closed"
    assert (await _fresh(db_session, old)).fail_reason == "not_created"


async def test_a_closed_sale_reported_in_hold_is_reopened(db_session: AsyncSession) -> None:
    """SB-1: nothing was paid on a closed sale; a late deposit follows the report."""
    sale = await make_sale(
        db_session, status="closed", fail_reason="not_created", attention_reason="late_deposit"
    )
    with capture_logs() as logs:
        assert await _apply(db_session, sale, deposit("hold")) == "hold"
    s = await _fresh(db_session, sale)
    assert (s.status, s.fail_reason, s.attention_reason) == ("hold", None, None)
    assert await _letters(db_session, sale) == ["sale_hold"]
    assert any(e["event"] == "sales.reopened" and e["was"] == "closed" for e in logs)


async def test_a_late_completed_deposit_credits_the_balance_once(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(
        db_session, status="closed", fail_reason="not_created", payout_uzs=Decimal(158_300)
    )
    assert await _apply(db_session, sale, deposit("completed")) == "credited"
    assert await _apply(db_session, sale, deposit("completed")) == "unchanged"
    assert (await _fresh(db_session, sale)).status == "credited"
    assert await user_balance(db_session, sale.user_id) == Decimal(158_300)
    assert await _credits(db_session, sale) == 1


async def test_a_late_card_deposit_reopens_its_canceled_request(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="closed", fail_reason="canceled", payout_to="card")
    await make_request(db_session, sale, status="canceled")
    assert await _apply(db_session, sale, deposit("hold")) == "hold"
    request = await request_of(db_session, sale.id)
    assert request is not None
    assert (request.status, request.to_pay_at) == ("waiting_hold", None)
    assert await _apply(db_session, sale, deposit("completed")) == "payout"
    request = await request_of(db_session, sale.id)
    assert request is not None
    assert request.status == "to_pay"
    assert request.to_pay_at is not None


async def test_a_late_completed_card_deposit_reopens_the_request_payable(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, status="reverted", payout_to="card")
    await make_request(db_session, sale, status="canceled")
    assert await _apply(db_session, sale, deposit("completed")) == "payout"
    request = await request_of(db_session, sale.id)
    assert request is not None
    assert request.status == "to_pay"
    assert request.to_pay_at is not None


async def test_a_closed_sale_reported_new_is_reopened_as_creating(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, status="closed", fail_reason="not_created")
    assert await _apply(db_session, sale, deposit("new")) == "reopened"
    assert (await _fresh(db_session, sale)).status == "creating"
    assert await _apply(db_session, sale, deposit("active")) == "offered"


async def test_a_reverted_sale_reported_completed_is_paid(db_session: AsyncSession) -> None:
    """SB-11: a reverted sale paid nothing, so a later ``completed`` is followed."""
    sale = await make_sale(db_session, status="reverted", payout_uzs=Decimal(158_300))
    assert await _apply(db_session, sale, deposit("completed")) == "credited"
    assert await user_balance(db_session, sale.user_id) == Decimal(158_300)


async def test_a_closed_sale_reported_failed_stays_closed(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="closed", fail_reason="canceled")
    assert await _apply(db_session, sale, deposit("failed")) == "unchanged"
    assert await _apply(db_session, sale, deposit("reverted")) == "attention"
    assert (await _fresh(db_session, sale)).status == "closed"


async def test_a_reverted_sale_reported_reverted_again_changes_nothing(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, status="reverted")
    assert await _apply(db_session, sale, deposit("reverted")) == "unchanged"
    assert await _apply(db_session, sale, deposit("canceled")) == "unchanged"


async def test_a_credited_sale_reported_completed_again_changes_nothing(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, status="credited")
    assert await _apply(db_session, sale, deposit("completed")) == "unchanged"


async def test_statuses_are_read_in_any_case(db_session: AsyncSession) -> None:
    """SB-9: ``Hold`` is ``hold``."""
    sale = await make_sale(db_session, status="offered")
    assert await _apply(db_session, sale, deposit("Hold")) == "hold"


async def test_a_new_attention_reason_reopens_a_resolved_one(db_session: AsyncSession) -> None:
    sale = await make_sale(
        db_session,
        status="credited",
        attention_reason="credit_blocked",
        resolved_at=now(),
        resolved_note="seen",
    )
    assert await _apply(db_session, sale, deposit("reverted")) == "attention"
    s = await _fresh(db_session, sale)
    assert (s.attention_reason, s.resolved_at, s.resolved_note) == ("rolled_back", None, None)


async def test_a_revert_clears_a_credit_blocked_flag(db_session: AsyncSession) -> None:
    """SB-13: nothing will be credited any more, so the flag has nothing left to say."""
    sale = await make_sale(db_session, status="offered", attention_reason="credit_blocked")
    assert await _apply(db_session, sale, deposit("reverted")) == "reverted"
    assert (await _fresh(db_session, sale)).attention_reason is None


async def test_a_closed_sale_reported_reverted_is_late_deposit_not_rolled_back(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, status="closed", fail_reason="not_created")
    assert await _apply(db_session, sale, deposit("reverted")) == "attention"
    s = await _fresh(db_session, sale)
    assert (s.status, s.attention_reason) == ("closed", "late_deposit")
    assert await _credits(db_session, sale) == 0


async def test_two_checks_at_once_credit_the_balance_once(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    sale = await make_sale(db_session, status="hold", payout_uzs=Decimal(158_300))
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def _check() -> Outcome:
        async with factory() as db:
            return await check_sale(
                db, FakeDepositClient(status=deposit("completed")), sale_id=sale.id
            )

    outcomes = await asyncio.gather(_check(), _check())
    assert sorted(outcomes) == ["credited", "unchanged"]
    assert await user_balance(db_session, sale.user_id) == Decimal(158_300)
    assert await _credits(db_session, sale) == 1


async def test_a_move_nudges_the_seller_on_commit(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="offered")
    async with listen_channel(CHANNEL) as events:
        assert await _apply(db_session, sale, deposit("hold")) == "hold"
        assert await events.drain() == [f"{sale.user_id}:{sale.number}:sale"]


async def test_check_sale_asks_the_status_and_applies_it(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="offered")
    client = FakeDepositClient(status=deposit("hold"))
    assert await check_sale(db_session, client, sale_id=sale.id) == "hold"
    assert client.status_calls == [sale.id]
    assert (await _fresh(db_session, sale)).last_polled_at is not None


async def test_check_sale_on_an_outage_changes_nothing(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="offered")
    client = FakeDepositClient(status=SkinslinkUnavailableError("down"))
    assert await check_sale(db_session, client, sale_id=sale.id) == "unchanged"
    assert (await _fresh(db_session, sale)).status == "offered"


async def test_a_failed_read_still_stamps_the_poll(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold")
    client = FakeDepositClient(status=SkinslinkUnavailableError("down"))
    assert await check_sale(db_session, client, sale_id=sale.id) == "unchanged"
    row = await _fresh(db_session, sale)
    assert row.status == "hold"
    assert row.last_polled_at is not None


async def test_a_sale_whose_read_keeps_failing_does_not_starve_the_next_batch(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    from csmarket.modules.sales.reconcile import poll_sales

    await make_sale(db_session, status="offered")
    client = FakeDepositClient(status=SkinslinkUnavailableError("down"))
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    at = now()
    assert await poll_sales(factory, client, at=at) == 1
    healthy = await make_sale(db_session, status="offered")
    later = at + timedelta(seconds=5)
    client.status = deposit("active")
    client.status_calls.clear()
    await poll_sales(factory, client, at=later)
    assert client.status_calls == [healthy.id]  # the broken one waits its interval


async def test_an_unknown_skinslink_status_is_logged_and_changes_nothing(
    db_session: AsyncSession,
) -> None:
    sale = await make_sale(db_session, status="offered")
    sample = {"outcome": "unknown"}
    before = REGISTRY.get_sample_value("csmarket_sale_outcomes_total", sample) or 0.0
    with capture_logs() as logs:
        assert await _apply(db_session, sale, deposit("weird")) == "unchanged"
    assert REGISTRY.get_sample_value("csmarket_sale_outcomes_total", sample) == before + 1
    assert any(
        e["event"] == "sales.unknown_status" and e["status"] == "weird" and e["sale"] == sale.number
        for e in logs
    )


async def test_a_frozen_wallet_leaves_the_sale_in_hold_flagged(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold", payout_uzs=Decimal(158_300))
    account = await user_account(db_session, sale.user_id)
    account.status = "frozen"
    await db_session.commit()
    client = FakeDepositClient(status=deposit("completed"))
    with capture_logs() as logs:
        assert await check_sale(db_session, client, sale_id=sale.id) == "attention"
    row = await _fresh(db_session, sale)
    assert (row.status, row.attention_reason, row.credited_at) == ("hold", "credit_blocked", None)
    assert any(e["event"] == "sales.attention" for e in logs)
    assert await _credits(db_session, sale) == 0
    # once unfrozen the next poll credits it and the flag clears
    account = await user_account(db_session, sale.user_id)
    account.status = "active"
    await db_session.commit()
    assert await check_sale(db_session, client, sale_id=sale.id) == "credited"
    row = await _fresh(db_session, sale)
    assert (row.status, row.attention_reason) == ("credited", None)


async def test_close_ends_only_a_creating_sale_and_counts_the_move(
    db_session: AsyncSession,
) -> None:
    creating = await make_sale(db_session, status="creating")
    offered = await make_sale(db_session, status="offered")
    for sale, want in ((creating, "closed"), (offered, "unchanged")):
        locked = await lock_sale(db_session, sale.id)
        assert locked is not None
        assert await close(db_session, locked, reason="profile_private") == want
        await db_session.commit()
    row = await _fresh(db_session, creating)
    assert (row.status, row.fail_reason) == ("closed", "profile_private")
    assert (await _fresh(db_session, offered)).status == "offered"
    assert await _letters(db_session, creating) == []
