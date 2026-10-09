"""Admin refund of a Skinslink / LIS-SKINS order, checked with the supplier first (plan C
Task 5, ADR-0018): refunded only when the supplier says the purchase failed, was cancelled or
returned — or never existed, for an old row with no buy running; no lock and no open
transaction across the supplier call."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterator, Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.core import config as cfg
from csmarket.core.errors import AppError
from csmarket.core.ids import new_id
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.lisskins.api import (
    InfoAnswer,
    LisskinsError,
    LisskinsUnavailableError,
    request_info_client,
)
from csmarket.modules.lisskins.api import Purchase as LisskinsReport
from csmarket.modules.orders import admin_refund_sources as sources
from csmarket.modules.orders.api import (
    Order,
    admin_refund,
    admin_refund_purchase,
    can_refund,
    purchase_refund_refusal,
)
from csmarket.modules.orders.api_checkout import create_api_order
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.purchase_rows import purchase_of
from csmarket.modules.public_api import keys
from csmarket.modules.public_api.auth import ApiCaller
from csmarket.modules.public_api.schemas import ApiOrderIn
from csmarket.modules.skinslink.api import (
    Purchase,
    SkinslinkError,
    SkinslinkPurchase,
    SkinslinkRateLimitedError,
    SkinslinkUnavailableError,
    request_status_client,
)
from csmarket.modules.wallet.api import user_balance, user_usd_balance
from csmarket.modules.wallet.models import WalletTransaction
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_lisskins_client import purchase as ls_purchase
from tests.integration.fake_skinslink_client import purchase as sl_purchase
from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.lisskins_factory import make_lisskins_order
from tests.integration.skinslink_factory import PRICE, make_skinslink_order
from tests.integration.test_public_api_buy import (
    _body,
    _customer,
    _env,  # noqa: F401 -- the autouse fixture: buying and Skinslink switched on
    _item,
)

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/orders"
OLD = timedelta(minutes=11)


class GuardedSkinslink:
    """Skinslink's ``purchase_status``: ``answer`` (a report, ``None`` = not found, or an
    exception); fails the test when asked with a transaction open on ``db``."""

    def __init__(self, db: AsyncSession | None, answer: Purchase | Exception | None) -> None:
        self.db, self.answer = db, answer
        self.calls: list[str] = []

    async def purchase_status(self, *, merchant_tx_id: str) -> Purchase | None:
        """The scripted answer."""
        if self.db is not None:
            assert not self.db.in_transaction(), "a transaction is open across Skinslink"
        self.calls.append(merchant_tx_id)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class GuardedLisskins:
    """LIS-SKINS' ``info_answer``: ``answer`` (the readable purchases, or an exception) and
    ``entries`` (the answer's entries, unreadable ones included; default: all readable),
    guarded the same."""

    def __init__(
        self,
        db: AsyncSession | None,
        answer: list[LisskinsReport] | Exception,
        *,
        entries: int | None = None,
    ) -> None:
        self.db, self.answer, self.entries = db, answer, entries
        self.calls: list[list[str]] = []

    async def info_answer(self, *, custom_ids: Sequence[str]) -> InfoAnswer:
        """The scripted answer."""
        if self.db is not None:
            assert not self.db.in_transaction(), "a transaction is open across LIS-SKINS"
        self.calls.append(list(custom_ids))
        if isinstance(self.answer, Exception):
            raise self.answer
        entries = len(self.answer) if self.entries is None else self.entries
        return InfoAnswer(purchases=tuple(self.answer), entries=entries)


class SlowSkinslink:
    """Never answers in time."""

    async def purchase_status(self, *, merchant_tx_id: str) -> Purchase | None:
        """Sleeps past the lookup's timeout."""
        await asyncio.sleep(5)
        return None  # pragma: no cover - cancelled by the timeout


def _unused_lisskins() -> GuardedLisskins:
    return GuardedLisskins(None, AssertionError("LIS-SKINS must not be asked"))


def _unused_skinslink() -> GuardedSkinslink:
    return GuardedSkinslink(None, AssertionError("Skinslink must not be asked"))


async def _code(call: Awaitable[object]) -> tuple[int, str | None]:
    with pytest.raises(AppError) as exc:
        await call
    return exc.value.status_code, exc.value.extra.get("code")


async def _refunds(db: AsyncSession) -> int:
    q = (
        select(func.count())
        .select_from(WalletTransaction)
        .where(WalletTransaction.kind == "refund")
    )
    return int(await db.scalar(q) or 0)


async def _fresh(db: AsyncSession, order_id: str) -> Order:
    await db.rollback()
    order = await db.scalar(
        select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    )
    assert order is not None
    return order


async def _sl_refund(db: AsyncSession, order: Order, answer: Purchase | Exception | None) -> Order:
    return await admin_refund_purchase(
        db,
        number=order.number,
        admin_id=new_id(),
        skinslink=GuardedSkinslink(db, answer),
        lisskins=_unused_lisskins(),
    )


async def _ls_refund(
    db: AsyncSession, order: Order, answer: list[LisskinsReport] | Exception
) -> Order:
    return await admin_refund_purchase(
        db,
        number=order.number,
        admin_id=new_id(),
        skinslink=_unused_skinslink(),
        lisskins=GuardedLisskins(db, answer),
    )


# --- Skinslink ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["failed", "canceled"])
async def test_a_failed_skinslink_purchase_is_refunded_in_som(
    db_session: AsyncSession, status: str
) -> None:
    order, _ = await make_skinslink_order(db_session, status="buying", purchase_status="active")
    order_id, user_id = order.id, order.user_id
    done = await _sl_refund(db_session, order, sl_purchase(status, merchant_tx_id=order_id))
    await db_session.commit()
    assert (done.status, done.failure_reason, done.refunded_to) == ("failed", "admin", "balance")
    assert await user_balance(db_session, user_id) == PRICE
    row = await db_session.get(SkinslinkPurchase, order_id)
    assert row is not None
    assert row.buy_pending is False


@pytest.mark.parametrize("status", ["active", "hold", "completed", "reverted", "pending"])
async def test_a_live_or_done_skinslink_purchase_is_never_refunded(
    db_session: AsyncSession, status: str
) -> None:
    """Review Focus 2: the supplier says the skin may reach the buyer — twice refused."""
    order, _ = await make_skinslink_order(db_session, status="trade_sent")
    order_id, user_id = order.id, order.user_id
    for _ in range(2):
        assert await _code(
            _sl_refund(db_session, order, sl_purchase(status, merchant_tx_id=order_id))
        ) == (409, "order_in_flight")
        await db_session.rollback()
    assert await _refunds(db_session) == 0
    assert await user_balance(db_session, user_id) == 0
    fresh = await _fresh(db_session, order_id)
    assert (fresh.status, fresh.refunded_at) == ("trade_sent", None)


async def test_a_second_click_after_a_refund_is_already_refunded(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session, status="buying")
    skinslink = GuardedSkinslink(db_session, sl_purchase("failed", merchant_tx_id=order.id))

    def refund() -> Awaitable[Order]:
        return admin_refund_purchase(
            db_session,
            number=order.number,
            admin_id=new_id(),
            skinslink=skinslink,
            lisskins=_unused_lisskins(),
        )

    await refund()
    await db_session.commit()
    assert await _code(refund()) == (409, "already_refunded")
    assert len(skinslink.calls) == 1  # refused before the supplier is asked again
    assert await _refunds(db_session) == 1


@pytest.mark.parametrize(
    "error",
    [
        SkinslinkUnavailableError("http 502"),
        SkinslinkRateLimitedError("429"),
        SkinslinkError("refused", status=400, code="x"),
    ],
)
async def test_a_failed_skinslink_lookup_refuses(
    db_session: AsyncSession, error: Exception
) -> None:
    order, _ = await make_skinslink_order(db_session, status="buying")
    assert await _code(_sl_refund(db_session, order, error)) == (409, "source_unavailable")
    assert await _refunds(db_session) == 0


async def test_a_slow_skinslink_lookup_times_out(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sources, "REFUND_LOOKUP_SECONDS", 0.05)
    order, _ = await make_skinslink_order(db_session, status="buying")
    refund = admin_refund_purchase(
        db_session,
        number=order.number,
        admin_id=new_id(),
        skinslink=SlowSkinslink(),
        lisskins=_unused_lisskins(),
    )
    assert await _code(refund) == (409, "source_unavailable")
    assert await _refunds(db_session) == 0


async def test_not_found_and_young_is_in_flight_without_asking(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(
        db_session, status="buying", purchase_id=None, purchase_status=None, offer_id=None
    )
    skinslink = GuardedSkinslink(db_session, None)
    refund = admin_refund_purchase(
        db_session,
        number=order.number,
        admin_id=new_id(),
        skinslink=skinslink,
        lisskins=_unused_lisskins(),
    )
    assert await _code(refund) == (409, "order_in_flight")
    assert skinslink.calls == []
    assert await _refunds(db_session) == 0


async def test_not_found_and_old_is_refunded(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(
        db_session,
        status="buying",
        purchase_id=None,
        purchase_status=None,
        offer_id=None,
        created_at=clock.now() - OLD,
    )
    done = await _sl_refund(db_session, order, None)
    assert done.status == "failed"
    assert await _refunds(db_session) == 1


async def test_not_found_with_a_purchase_on_record_is_in_flight(db_session: AsyncSession) -> None:
    """Skinslink once reported purchase 178 for this order; «not found» now proves nothing."""
    order, _ = await make_skinslink_order(db_session, status="buying", created_at=clock.now() - OLD)
    assert await _code(_sl_refund(db_session, order, None)) == (409, "order_in_flight")
    assert await _refunds(db_session) == 0


async def test_a_running_buy_is_busy_without_asking(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(
        db_session, status="buying", buy_pending=True, created_at=clock.now() - OLD
    )
    order.next_check_at = clock.now() + timedelta(minutes=3)
    await db_session.commit()
    assert await _code(_sl_refund(db_session, order, None)) == (409, "order_busy")


async def test_an_unresolved_attention_must_be_checked_first(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(
        db_session, status="buying", attention_reason="buy_unconfirmed"
    )
    assert await _code(_sl_refund(db_session, order, sl_purchase("failed"))) == (
        409,
        "order_needs_attention",
    )


@pytest.mark.parametrize("status", ["paid", "delivered", "failed", "returned", "cancelled"])
async def test_only_buying_or_trade_sent_orders(db_session: AsyncSession, status: str) -> None:
    order, _ = await make_skinslink_order(db_session, status=status)
    assert await _code(_sl_refund(db_session, order, sl_purchase("failed"))) == (
        409,
        "order_not_refundable",
    )


async def test_the_order_moving_during_the_lookup_is_rechecked(db_session: AsyncSession) -> None:
    """A purchase id recorded while the supplier answered: its «not found» no longer covers it."""
    order, _ = await make_skinslink_order(
        db_session,
        status="buying",
        purchase_id=None,
        purchase_status=None,
        created_at=clock.now() - OLD,
    )
    order_id = order.id

    class Racing(GuardedSkinslink):
        async def purchase_status(self, *, merchant_tx_id: str) -> Purchase | None:
            await super().purchase_status(merchant_tx_id=merchant_tx_id)
            row = await db_session.get(SkinslinkPurchase, order_id)
            assert row is not None
            row.purchase_id = 999
            await db_session.commit()
            return None

    refund = admin_refund_purchase(
        db_session,
        number=order.number,
        admin_id=new_id(),
        skinslink=Racing(db_session, None),
        lisskins=_unused_lisskins(),
    )
    assert await _code(refund) == (409, "order_in_flight")
    assert await _refunds(db_session) == 0


async def test_an_api_order_is_refunded_to_the_usd_wallet(
    customer_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    user, _ = await _customer(db_session, customer_headers, profile="cost")
    key = await keys.live_key(db_session, user.id)
    assert key is not None
    order, _ = await create_api_order(
        db_session,
        caller=ApiCaller(key=key, user=user),
        body=ApiOrderIn.model_validate(_body(item)),
        settings=cfg.get_settings(),
    )
    move(order, "buying")
    db_session.add(
        SkinslinkPurchase(
            order_id=order.id,
            merchant_tx_id=order.id,
            asset_id="100",
            paid_units=9000,
            purchase_id=178,
            buy_pending=False,
        )
    )
    await db_session.commit()
    user_id = user.id
    uzs_before = await user_balance(db_session, user_id)
    assert await user_usd_balance(db_session, user_id) == Decimal(50_000 - 9000)
    await _sl_refund(db_session, order, sl_purchase("failed", merchant_tx_id=order.id))
    await db_session.commit()
    assert await user_usd_balance(db_session, user_id) == Decimal(50_000)
    assert await user_balance(db_session, user_id) == uzs_before


@pytest.mark.parametrize("source", ["skinslink", "lisskins"])
async def test_a_fresh_lost_answer_is_never_refunded_on_not_found(
    db_session: AsyncSession, source: str
) -> None:
    """An old row whose latest buy answer was lost a minute ago: the source may not show the
    purchase yet — a silence is never refunded."""
    lost: dict[str, Any] = {
        "status": "buying",
        "purchase_id": None,
        "created_at": clock.now() - OLD,
        "buy_unconfirmed_at": clock.now() - timedelta(minutes=1),
    }
    if source == "skinslink":
        order, _ = await make_skinslink_order(db_session, purchase_status=None, **lost)
        refund = _sl_refund(db_session, order, None)
    else:
        order, _ = await make_lisskins_order(db_session, skin_status=None, **lost)
        refund = _ls_refund(db_session, order, [])
    assert await _code(refund) == (409, "order_in_flight")
    assert await _refunds(db_session) == 0


@pytest.mark.parametrize(
    "report",
    [
        {"merchant_tx_id": "someone-else"},
        {"merchant_tx_id": None},
        {"id": 999},  # our row says purchase 178
    ],
)
async def test_a_skinslink_answer_about_another_purchase_is_not_ours(
    db_session: AsyncSession, report: dict[str, Any]
) -> None:
    order, _ = await make_skinslink_order(db_session, status="buying")
    answer = sl_purchase("failed", **{"merchant_tx_id": order.id, **report})
    assert await _code(_sl_refund(db_session, order, answer)) == (409, "order_in_flight")
    assert await _refunds(db_session) == 0


async def test_a_lost_answer_recorded_during_the_lookup_is_rechecked(
    db_session: AsyncSession,
) -> None:
    order, _ = await make_skinslink_order(
        db_session,
        status="buying",
        purchase_id=None,
        purchase_status=None,
        created_at=clock.now() - OLD,
    )
    order_id = order.id

    class Racing(GuardedSkinslink):
        async def purchase_status(self, *, merchant_tx_id: str) -> Purchase | None:
            await super().purchase_status(merchant_tx_id=merchant_tx_id)
            row = await db_session.get(SkinslinkPurchase, order_id)
            assert row is not None
            row.buy_unconfirmed_at = clock.now()
            await db_session.commit()
            return None

    refund = admin_refund_purchase(
        db_session,
        number=order.number,
        admin_id=new_id(),
        skinslink=Racing(db_session, None),
        lisskins=_unused_lisskins(),
    )
    assert await _code(refund) == (409, "order_in_flight")
    assert await _refunds(db_session) == 0


# --- LIS-SKINS ---------------------------------------------------------------------------


async def test_a_returned_lisskins_purchase_is_refunded(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session, skin_status="wait_accept")
    order_id, user_id = order.id, order.user_id
    lisskins = GuardedLisskins(db_session, [ls_purchase("return", custom_id=order_id)])
    done = await admin_refund_purchase(
        db_session,
        number=order.number,
        admin_id=new_id(),
        skinslink=_unused_skinslink(),
        lisskins=lisskins,
    )
    await db_session.commit()
    assert lisskins.calls == [[order_id]]
    # A trade_sent order's offer died: ``returned`` (the FSM has no trade_sent → failed).
    assert (done.status, done.failure_reason) == ("returned", "admin")
    assert await user_balance(db_session, user_id) == PRICE


@pytest.mark.parametrize(
    ("status", "more"),
    [
        ("accepted", {}),
        ("wait_accept", {}),
        ("processing", {}),
        ("wait_unlock", {}),
        ("wait_withdraw", {}),
        ("return", {"return_reason": "rollback_buyer"}),
    ],
)
async def test_a_live_or_accepted_lisskins_purchase_is_never_refunded(
    db_session: AsyncSession, status: str, more: dict[str, Any]
) -> None:
    order, _ = await make_lisskins_order(db_session)
    order_id = order.id
    for _ in range(2):
        report = [ls_purchase(status, custom_id=order_id, **more)]
        assert await _code(_ls_refund(db_session, order, report)) == (409, "order_in_flight")
        await db_session.rollback()
    assert await _refunds(db_session) == 0
    assert (await _fresh(db_session, order_id)).refunded_at is None


async def test_another_custom_id_in_the_answer_is_not_ours(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session, created_at=clock.now() - OLD)
    report = [ls_purchase("return", custom_id="someone-else")]
    # Purchase 55 is on record: an answer without our custom id proves nothing.
    assert await _code(_ls_refund(db_session, order, report)) == (409, "order_in_flight")


async def test_another_custom_id_is_not_ours_even_with_no_purchase_on_record(
    db_session: AsyncSession,
) -> None:
    order, _ = await make_lisskins_order(
        db_session,
        status="buying",
        skin_status=None,
        purchase_id=None,
        created_at=clock.now() - OLD,
    )
    report = [ls_purchase("return", custom_id="someone-else")]
    assert await _code(_ls_refund(db_session, order, report)) == (409, "order_in_flight")
    assert await _refunds(db_session) == 0


@pytest.mark.parametrize("ours", [False, True])
async def test_an_unreadable_lisskins_entry_is_never_not_found(
    db_session: AsyncSession, ours: bool
) -> None:
    """LIS-SKINS sent an entry ``info`` could not read: it may be our purchase."""
    order, _ = await make_lisskins_order(
        db_session,
        status="buying",
        skin_status=None,
        purchase_id=None,
        created_at=clock.now() - OLD,
    )
    readable = [ls_purchase("return", custom_id=order.id, purchase_id=55)] if ours else []
    lisskins = GuardedLisskins(db_session, readable, entries=len(readable) + 1)
    refund = admin_refund_purchase(
        db_session,
        number=order.number,
        admin_id=new_id(),
        skinslink=_unused_skinslink(),
        lisskins=lisskins,
    )
    assert await _code(refund) == (409, "order_in_flight")
    assert await _refunds(db_session) == 0


async def test_a_lisskins_answer_with_another_purchase_id_is_not_ours(
    db_session: AsyncSession,
) -> None:
    order, _ = await make_lisskins_order(db_session)  # purchase 55 on record
    report = [ls_purchase("return", custom_id=order.id, purchase_id=77)]
    assert await _code(_ls_refund(db_session, order, report)) == (409, "order_in_flight")
    assert await _refunds(db_session) == 0


async def test_lisskins_not_found_and_old_is_refunded(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(
        db_session,
        status="buying",
        skin_status=None,
        purchase_id=None,
        created_at=clock.now() - OLD,
    )
    assert (await _ls_refund(db_session, order, [])).status == "failed"


@pytest.mark.parametrize(
    "error",
    [LisskinsUnavailableError("http 502"), LisskinsError("refused", status=400, code="x")],
)
async def test_a_failed_lisskins_lookup_refuses(db_session: AsyncSession, error: Exception) -> None:
    order, _ = await make_lisskins_order(db_session)
    assert await _code(_ls_refund(db_session, order, error)) == (409, "source_unavailable")
    assert await _refunds(db_session) == 0


# --- the refusal, the detail and the route ---------------------------------------------


async def test_the_refusal_without_a_supplier_call(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session, status="trade_sent")
    row = await purchase_of(db_session, order, lock=False)
    at = clock.now()
    assert purchase_refund_refusal(order, row, at) is None
    assert purchase_refund_refusal(order, None, at) == "order_not_refundable"
    # Stored «active»: the action would ask Skinslink, but the button stays hidden.
    assert can_refund(order, None, at, purchase=row) is False
    quiet, _ = await make_skinslink_order(
        db_session, status="trade_sent", purchase_status="failed", purchase_id=179
    )
    quiet_row = await purchase_of(db_session, quiet, lock=False)
    assert can_refund(quiet, None, at, purchase=quiet_row) is True
    young, _ = await make_skinslink_order(db_session, status="buying", purchase_id=None)
    young_row = await purchase_of(db_session, young, lock=False)
    assert purchase_refund_refusal(young, young_row, at) == "order_in_flight"
    assert can_refund(young, None, at, purchase=young_row) is False


async def test_admin_refund_dispatches_by_source(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session)
    lisskins = GuardedLisskins(db_session, [ls_purchase("return", custom_id=order.id)])
    done = await admin_refund(
        db_session,
        number=order.number,
        admin_id=new_id(),
        client=FakeTradeClient(),
        skinslink=_unused_skinslink(),
        lisskins=lisskins,
    )
    assert done.refunded_at is not None
    assert len(lisskins.calls) == 1


@pytest.fixture
def suppliers(integration_app: FastAPI) -> Iterator[dict[str, Any]]:
    """The route's supplier clients, swapped per test (``answer`` set by the test)."""
    fakes: dict[str, Any] = {
        "skinslink": GuardedSkinslink(None, None),
        "lisskins": GuardedLisskins(None, []),
    }
    integration_app.dependency_overrides[request_status_client] = lambda: fakes["skinslink"]
    integration_app.dependency_overrides[request_info_client] = lambda: fakes["lisskins"]
    yield fakes
    integration_app.dependency_overrides.pop(request_status_client, None)
    integration_app.dependency_overrides.pop(request_info_client, None)


async def test_the_route_refunds_audits_and_shows_can_refund(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    suppliers: dict[str, Any],
) -> None:
    h = await admin_headers()
    live, _ = await make_skinslink_order(db_session, status="trade_sent")
    page = await integration_client.get(f"{BASE}/{live.number}", headers=h)
    assert page.json()["can_refund"] is False  # stored «active»: no button
    order, _ = await make_skinslink_order(
        db_session, status="trade_sent", purchase_status=None, purchase_id=179
    )
    page = await integration_client.get(f"{BASE}/{order.number}", headers=h)
    assert page.json()["can_refund"] is True
    suppliers["skinslink"].answer = sl_purchase("active", merchant_tx_id=order.id)
    key = {"Idempotency-Key": f"admin-refund-{uuid.uuid4()}"}
    r = await integration_client.post(f"{BASE}/{order.number}/refund", headers={**h, **key})
    assert (r.status_code, r.json()["code"]) == (409, "order_in_flight")
    suppliers["skinslink"].answer = SkinslinkUnavailableError("down")
    r = await integration_client.post(f"{BASE}/{order.number}/refund", headers={**h, **key})
    assert (r.status_code, r.json()["code"]) == (409, "source_unavailable")
    suppliers["skinslink"].answer = sl_purchase("canceled", merchant_tx_id=order.id, id=179)
    r = await integration_client.post(f"{BASE}/{order.number}/refund", headers={**h, **key})
    assert r.status_code == 200, r.text
    assert (r.json()["order"]["status"], r.json()["can_refund"]) == ("returned", False)
    again = await integration_client.post(f"{BASE}/{order.number}/refund", headers={**h, **key})
    assert (again.status_code, again.json()) == (200, r.json())
    (row,) = await db_session.scalars(
        select(AdminAuditLog).where(AdminAuditLog.action == "orders.refund")
    )
    assert (row.target_id, row.payload) == (order.number, {"amount_uzs": int(PRICE)})
    assert await _refunds(db_session) == 1


@pytest.mark.parametrize("number", ["nope", "T7K2M9QX", "Z9Z9Z9Z9"])
async def test_an_unknown_number_is_not_found(db_session: AsyncSession, number: str) -> None:
    refund = admin_refund_purchase(
        db_session,
        number=number,
        admin_id=new_id(),
        skinslink=_unused_skinslink(),
        lisskins=_unused_lisskins(),
    )
    assert (await _code(refund))[0] == 404
    waxpeer = admin_refund(db_session, number=number, admin_id=new_id(), client=FakeTradeClient())
    assert (await _code(waxpeer))[0] == 404


async def test_a_supplier_order_without_its_client_is_refused(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session, status="buying")
    refund = admin_refund(
        db_session, number=order.number, admin_id=new_id(), client=FakeTradeClient()
    )
    assert await _code(refund) == (409, "source_unavailable")
    assert await _refunds(db_session) == 0


def test_the_route_clients_answer_within_four_seconds() -> None:
    """The real dependencies: one lookup each, bounded like the Waxpeer refund's."""
    assert request_status_client()._timeout == 4.0
    assert request_info_client()._timeout == 4.0
