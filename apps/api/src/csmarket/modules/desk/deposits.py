"""A deal's skins sent to Skinslink, and the deposit followed to the end (spec 2026-10-29-desk
«Selling to Skinslink»).

The deposit row is committed ``creating`` (its items ``sent``) before the one
``create-deposit`` call, nothing open across it; ``merchant_tx_id`` is ``desk-{id}``. A lost
answer is left ``creating`` for the poll, which asks ``deposit/status`` under the same id —
never a second create. ``already_exists`` is adopted the same way. The shop's selling
switches, limits and risk holds do not apply (the owner's own tool, ADR-0027).

What a report does (:func:`apply_report`): accepted (``hold`` / ``completed``) → the deal is
``received``; ``completed`` with an amount → each item ``credited`` with its share of the
amount (``money.split_revenue``) and a ``credit`` row of ``share − cost``; ``failed`` /
``canceled`` → the items go back to ``open``; ``reverted`` → the items ``reverted``, the deal
``reverted``, and after a credit a ``revert`` row per item undoing its revenue, dated now.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import Text, cast, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.modules.desk.deals import close_if_done, items_of, load_deal
from csmarket.modules.desk.inventory import refused, unavailable
from csmarket.modules.desk.models import (
    DEPOSIT_DEAD,
    DESK_TX_PREFIX,
    DeskDeal,
    DeskDeposit,
    DeskEntry,
    DeskItem,
)
from csmarket.modules.desk.money import split_revenue
from csmarket.modules.sales.api import min_prices
from csmarket.modules.skinslink.api import (
    PRICE_CODES,
    Deposit,
    DepositClient,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)
from csmarket.modules.users.api import parse_tradelink

log = get_logger("csmarket.desk.deposits")

#: A ``creating`` deposit Skinslink does not know is given up after this (as SB-1 in sales).
NOT_FOUND_GRACE = timedelta(minutes=10)
LIVE_EVERY = timedelta(minutes=1)
HOLD_EVERY = timedelta(minutes=30)
#: After a credit we keep asking while the trader may still reverse (7 days + a day).
WATCH_AFTER_ACCEPT = timedelta(days=8)
WATCH_EVERY = timedelta(hours=1)
_OPEN = ("creating", "new", "pending", "active")
#: Far enough that a settled deposit is never due again.
_NEVER = timedelta(days=3650)


def _tx_id(deposit_id: str) -> str:
    return f"{DESK_TX_PREFIX}{deposit_id}"


async def _sent_items(db: AsyncSession, deposit_id: str) -> list[DeskItem]:
    rows = await db.scalars(select(DeskItem).where(DeskItem.deposit_id == deposit_id))
    return sorted(rows.all(), key=lambda i: i.id)


async def _free(db: AsyncSession, deposit_id: str) -> None:
    """The deposit's ``sent`` items back to ``open``, unbound."""
    await db.execute(
        update(DeskItem)
        .where(DeskItem.deposit_id == deposit_id, DeskItem.state == "sent")
        .values(state="open", deposit_id=None)
    )


async def _fail(db: AsyncSession, deposit: DeskDeposit, reason: str) -> None:
    deposit.status = "failed"
    deposit.fail_reason = reason[:64]
    await _free(db, deposit.id)


async def _credit(db: AsyncSession, deal: DeskDeal, deposit: DeskDeposit, at: datetime) -> None:
    items = [i for i in await _sent_items(db, deposit.id) if i.state == "sent"]
    shares = split_revenue(deposit.amount_usd or Decimal(0), [i.skinslink_usd for i in items])
    for item, revenue in zip(items, shares, strict=True):
        item.state = "credited"
        item.resolved_at = at
        db.add(
            DeskEntry(
                id=new_id(),
                deal_id=deal.id,
                item_id=item.id,
                kind="credit",
                revenue_usd=revenue,
                profit_usd=revenue - (item.cost_usd or Decimal(0)),
                at=at,
            )
        )
    deposit.credited_at = at
    await db.flush()
    await close_if_done(db, deal)


async def _revert(db: AsyncSession, deal: DeskDeal, deposit: DeskDeposit, at: datetime) -> None:
    deposit.reverted_at = at
    credited = {
        e.item_id: e
        for e in await db.scalars(
            select(DeskEntry).where(
                DeskEntry.deal_id == deal.id,
                DeskEntry.kind == "credit",
                DeskEntry.item_id.in_(select(DeskItem.id).where(DeskItem.deposit_id == deposit.id)),
            )
        )
    }
    for item in await _sent_items(db, deposit.id):
        if item.state not in ("sent", "credited"):
            continue
        item.state = "reverted"
        item.resolved_at = at
        if (credit := credited.get(item.id)) is not None:
            db.add(
                DeskEntry(
                    id=new_id(),
                    deal_id=deal.id,
                    item_id=item.id,
                    kind="revert",
                    revenue_usd=-credit.revenue_usd,
                    profit_usd=-credit.revenue_usd,
                    at=at,
                )
            )
    deal.status = "reverted"
    deal.updated_at = at


def _next_check(deposit: DeskDeposit, at: datetime) -> datetime:
    if deposit.status in DEPOSIT_DEAD:
        return at + _NEVER
    if deposit.status == "hold":
        return at + HOLD_EVERY
    if deposit.status == "completed":
        accepted = deposit.accepted_at or at
        return at + WATCH_EVERY if at < accepted + WATCH_AFTER_ACCEPT else at + _NEVER
    return at + LIVE_EVERY


async def apply_report(
    db: AsyncSession, deposit: DeskDeposit, report: Deposit | None, *, at: datetime
) -> None:
    """Bring the deposit, its items and its deal up to Skinslink's report (``None``: unknown)."""
    deal = await load_deal(db, deposit.deal_id, lock=True)
    if report is None:
        if deposit.status == "creating" and deposit.created_at < at - NOT_FOUND_GRACE:
            await _fail(db, deposit, "not_found")
    else:
        deposit.skinslink_id = report.id
        deposit.status = report.status
        if report.amount_usd is not None:
            deposit.amount_usd = report.amount_usd
        deposit.trade_offer_id = report.trade_offer_id or deposit.trade_offer_id
        deposit.offer_expiry_at = report.offer_expiry_at or deposit.offer_expiry_at
        deposit.hold_end_date = report.hold_end_date or deposit.hold_end_date
        deposit.fail_reason = report.fail_reason
        if report.status in ("hold", "completed") and deposit.accepted_at is None:
            deposit.accepted_at = at
            if deal.status in ("agreed", "paid"):
                deal.status = "received"
                deal.updated_at = at
        if report.status in ("failed", "canceled"):
            await _free(db, deposit.id)
        elif report.status == "reverted" and deposit.reverted_at is None:
            await _revert(db, deal, deposit, at)
        elif (
            report.status == "completed"
            and deposit.amount_usd is not None
            and deposit.credited_at is None
        ):
            await _credit(db, deal, deposit, at)
    deposit.next_check_at = _next_check(deposit, at)
    await db.flush()


async def send(db: AsyncSession, client: DepositClient, deal_id: str) -> DeskDeal:
    """«Отправить обмен»: one deposit for the deal's open Skinslink items with an asset id.

    Raises:
        NotFoundError: ``deal_not_found``.
        ConflictError: ``trade_link_missing``, ``deposit_open``, ``nothing_to_send``,
            ``prices_moved``, ``steam_refused``.
        DeskUnavailableError: ``desk_unavailable`` — refused otherwise, or a 403.
    """
    deal = await load_deal(db, deal_id, lock=True)
    if not deal.trade_link:
        raise ConflictError("the deal has no trade link", code="trade_link_missing")
    link = parse_tradelink(deal.trade_link)
    open_one = await db.scalar(
        select(DeskDeposit.id).where(DeskDeposit.deal_id == deal.id, DeskDeposit.status.in_(_OPEN))
    )
    if open_one is not None:
        raise ConflictError("a deposit of this deal is still open", code="deposit_open")
    items = [
        i
        for i in await items_of(db, deal.id)
        if i.destination == "skinslink" and i.state == "open" and i.asset_id
    ]
    if not items:
        raise ConflictError("no skins to send", code="nothing_to_send")
    deposit = DeskDeposit(
        id=new_id(), deal_id=deal.id, status="creating", next_check_at=now() + LIVE_EVERY
    )
    db.add(deposit)
    await db.flush()
    for item in items:
        item.state = "sent"
        item.deposit_id = deposit.id
    await db.commit()
    floors = min_prices([(i.asset_id or "", i.skinslink_usd) for i in items if i.skinslink_usd])
    try:
        report = await client.create_deposit(
            merchant_tx_id=_tx_id(deposit.id),
            partner=link.partner,
            token=link.token,
            asset_ids=[i.asset_id or "" for i in items],
            min_prices=floors,
        )
    except SkinslinkForbiddenError:
        await _settle_failure(db, deposit.id, "forbidden")
        raise unavailable() from None
    except SkinslinkError as exc:
        if exc.code == "already_exists":  # the call landed after all
            await check_deposit(db, client, deposit_id=deposit.id)
            return await load_deal(db, deal_id)
        await _settle_failure(db, deposit.id, exc.code or f"http_{exc.status}")
        if exc.code in PRICE_CODES:
            raise ConflictError(
                "Skinslink's prices moved; load the inventory again", code="prices_moved"
            ) from None
        raise refused(exc) from None
    except SkinslinkUnavailableError as exc:
        log.warning("desk.deposit_unanswered", error=type(exc).__name__)
        return await load_deal(db, deal_id)
    locked = await _lock(db, deposit.id)
    if locked is not None:
        await apply_report(db, locked, report, at=now())
        await db.commit()
    return await load_deal(db, deal_id)


async def _lock(db: AsyncSession, deposit_id: str) -> DeskDeposit | None:
    return await db.scalar(
        select(DeskDeposit)
        .where(DeskDeposit.id == deposit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _settle_failure(db: AsyncSession, deposit_id: str, reason: str) -> None:
    locked = await _lock(db, deposit_id)
    if locked is not None:
        await _fail(db, locked, reason)
        locked.next_check_at = now() + _NEVER
        await db.commit()


async def check_deposit(db: AsyncSession, client: DepositClient, *, deposit_id: str) -> None:
    """Ask Skinslink about one deposit and apply the answer; an outage changes only when
    it is asked next."""
    await db.commit()
    try:
        report = await client.deposit_status(merchant_tx_id=_tx_id(deposit_id))
    except (SkinslinkError, SkinslinkUnavailableError) as exc:
        log.warning("desk.status_unread", error=type(exc).__name__)
        await db.execute(
            update(DeskDeposit)
            .where(DeskDeposit.id == deposit_id)
            .values(next_check_at=now() + LIVE_EVERY)
        )
        await db.commit()
        return
    locked = await _lock(db, deposit_id)
    if locked is None:
        await db.rollback()
        return
    await apply_report(db, locked, report, at=now())
    await db.commit()


async def mark_due(db: AsyncSession, merchant_tx_id: object) -> bool:
    """The webhook's hand-off: a known desk deposit is asked about on the next poll.

    Returns:
        ``False`` for anything but one of our ``desk-`` ids.
    """
    if not isinstance(merchant_tx_id, str) or not merchant_tx_id.startswith(DESK_TX_PREFIX):
        return False
    raw = merchant_tx_id[len(DESK_TX_PREFIX) :]
    result = await db.execute(
        update(DeskDeposit).where(cast(DeskDeposit.id, Text) == raw).values(next_check_at=now())
    )
    return bool(getattr(result, "rowcount", 0))  # CursorResult; typed as Result


async def due_deposits(db: AsyncSession, *, at: datetime, limit: int = 100) -> list[str]:
    """Deposits whose next check has come, oldest due first."""
    rows = await db.scalars(
        select(DeskDeposit.id)
        .where(DeskDeposit.status.not_in(DEPOSIT_DEAD), DeskDeposit.next_check_at <= at)
        .order_by(DeskDeposit.next_check_at)
        .limit(limit)
    )
    return [str(r) for r in rows]


__all__ = [
    "NOT_FOUND_GRACE",
    "apply_report",
    "check_deposit",
    "due_deposits",
    "mark_due",
    "send",
]
