# apps/api/src/csmarket/modules/sales/service.py
"""``POST /sell``: a sale from the seller's kept inventory, then one ``create-deposit``.

Re-prices the chosen items from the snapshot the seller saw (Redis, 5 min — never the
browser's numbers), checks the switches, the minimums, ``max_items`` and that the payout is
the one the cart showed, stores the sale (``creating``), its items and a new card in one
transaction and commits; only then calls Skinslink — one call, nothing open across it (AGENTS
§11, ADR-0016). Its answer is applied by :func:`.status.apply_deposit`, like any later
status. ``min_prices`` floors every item at 99 % of its quoted price; the seller's payout is
fixed here, whatever Skinslink credits above the floor (spec §3).

A refusal closes the sale (``fail_reason`` = the code) and answers 409 (``prices_changed``
also drops the kept snapshot); a 403 closes it and answers 503; an outage or a timeout leaves
it ``creating`` for the poll; ``409 already exist`` — the call landed after all — is adopted
through ``deposit/status``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.errors import ConflictError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.core.money import wire_uzs
from csmarket.core.numbers import allocate, sale_number
from csmarket.modules.sales.cards import add_card, card_digits, owned_card
from csmarket.modules.sales.gate import open_settings, sale_rate_now, trade_link_of
from csmarket.modules.sales.inventory import (
    Snapshot,
    cached_snapshot,
    forget_snapshot,
    unavailable,
)
from csmarket.modules.sales.models import Sale, SaleItem
from csmarket.modules.sales.pricing import (
    ItemQuote,
    Payout,
    min_prices,
    min_sum_uzs,
    payout_for,
    quote_item,
)
from csmarket.modules.sales.rules import CardType, PayoutTo, SaleSettings
from csmarket.modules.sales.schemas import PayoutIn, SellIn
from csmarket.modules.sales.status import apply_deposit, check_sale, close, lock_sale
from csmarket.modules.skinslink.api import (
    PRICE_CODES,
    STEAM_ACCOUNT_CODES,
    Deposit,
    DepositClient,
    InventoryItem,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)
from csmarket.modules.users.api import TradeLink, User

log = get_logger("csmarket.sales.service")

_USD = Decimal("0.000001")


@dataclass(frozen=True)
class _Draft:
    """Everything the sale row needs, checked; nothing written yet."""

    user_id: str
    link: TradeLink = field(repr=False)
    rate: Decimal
    chosen: list[InventoryItem]
    quotes: list[ItemQuote]
    payout: Payout
    #: The snapshot's cap per sale (Skinslink's own refusal does not carry it).
    max_items: int
    payout_to: PayoutTo
    card_id: str | None
    #: ``(type, digits)`` of a card typed in the cart. PII: never in a repr or a log.
    new_card: tuple[CardType, str] | None = field(repr=False)

    @property
    def quoted_usd(self) -> Decimal:
        return sum((i.price_usd for i in self.chosen), Decimal(0))

    @property
    def margin_usd(self) -> Decimal:
        return sum((q.margin_usd for q in self.quotes), Decimal(0))


def _prices_changed() -> ConflictError:
    return ConflictError("prices changed; read the inventory again", code="prices_changed")


async def _by_key(db: AsyncSession, user_id: str, key: str) -> Sale | None:
    return await db.scalar(select(Sale).where(Sale.user_id == user_id, Sale.idempotency_key == key))


def _pick(snap: Snapshot, asset_ids: Sequence[str]) -> list[InventoryItem]:
    """The chosen items from the kept snapshot, in the order asked (duplicates once)."""
    wanted = list(dict.fromkeys(asset_ids))
    if len(wanted) > snap.max_items:
        raise ConflictError(
            "too many items for one sale", code="too_many_items", max_items=snap.max_items
        )
    by_id = {i.id: i for i in snap.items}
    if any(a not in by_id for a in wanted):
        raise _prices_changed()
    return [by_id[a] for a in wanted]


async def _card(
    db: AsyncSession, user_id: str, payout: PayoutIn
) -> tuple[CardType | None, str | None, tuple[CardType, str] | None]:
    """``(card type, saved card id, new card)`` of the payout; all ``None`` for the balance."""
    if payout.to == "balance":
        return None, None, None
    if payout.card_id is not None:
        card = await owned_card(db, user_id=user_id, card_id=str(payout.card_id))
        kind: CardType = card.type  # type: ignore[assignment]  # the column's check
        return kind, card.id, None
    if payout.new_card is None:  # PayoutIn's validator makes this unreachable
        raise ValueError("a card payout without a card")
    new = payout.new_card
    return new.type, None, (new.type, card_digits(new.type, new.number))


def _check_minimums(
    doc: SaleSettings, rate: Decimal, quoted: Decimal, payout: Payout, to: PayoutTo
) -> None:
    if quoted < doc.min_sum_usd:
        raise ConflictError(
            "the items are worth less than the minimum",
            code="below_minimum",
            min_sum_uzs=wire_uzs(min_sum_uzs(doc, rate)),
        )
    if to == "card" and payout.payout_uzs < doc.card_min_uzs:
        raise ConflictError(
            "a card payout is under the minimum",
            code="below_card_minimum",
            card_min_uzs=str(doc.card_min_uzs),
        )


async def _draft(
    db: AsyncSession, redis: Redis, user: User, body: SellIn, settings: Settings
) -> _Draft:
    """Every check and every number of the sale, from the kept snapshot."""
    doc = await open_settings(db, settings)
    link = trade_link_of(user)
    rate = await sale_rate_now(db, redis, settings, doc)
    snap = await cached_snapshot(redis, user.id, link.url)
    if snap is None:
        raise _prices_changed()
    chosen = _pick(snap, body.asset_ids)
    quotes = [quote_item(i.price_usd, doc, rate) for i in chosen]
    if any(q.price_uzs <= 0 for q in quotes):  # hidden from the list: never sold for nothing
        raise _prices_changed()
    card_type, card_id, new_card = await _card(db, user.id, body.payout)
    items_uzs = sum((q.price_uzs for q in quotes), Decimal(0))
    payout = payout_for(items_uzs, doc, to=body.payout.to, card_type=card_type)
    quoted = sum((i.price_usd for i in chosen), Decimal(0))
    _check_minimums(doc, rate, quoted, payout, body.payout.to)
    if payout.payout_uzs != body.expected_payout_uzs:
        raise _prices_changed()
    return _Draft(
        user_id=user.id,
        link=link,
        rate=rate,
        chosen=chosen,
        quotes=quotes,
        payout=payout,
        max_items=snap.max_items,
        payout_to=body.payout.to,
        card_id=card_id,
        new_card=new_card,
    )


async def _store(db: AsyncSession, draft: _Draft, key: str) -> tuple[Sale, bool]:
    """The sale, its items and a new card in one transaction; a key that raced us replays."""
    card_id = draft.card_id
    if draft.new_card is not None:
        card_type, digits = draft.new_card
        card = await add_card(db, user_id=draft.user_id, card_type=card_type, raw_number=digits)
        card_id = card.id
    sale = Sale(
        id=new_id(),
        number=await allocate(db, Sale.number, sale_number),
        user_id=draft.user_id,
        status="creating",
        payout_to=draft.payout_to,
        payout_card_id=card_id,
        quoted_usd=draft.quoted_usd.quantize(_USD),
        items_uzs=draft.payout.items_uzs,
        payout_uzs=draft.payout.payout_uzs,
        rate=draft.rate,
        margin_usd=draft.margin_usd.quantize(_USD),
        idempotency_key=key,
    )
    db.add(sale)
    db.add_all(
        SaleItem(
            sale_id=sale.id,
            asset_id=item.id,
            name=item.name[:255],
            image_url=item.image_url,
            price_usd=item.price_usd.quantize(_USD),
            price_uzs=quote.price_uzs,
        )
        for item, quote in zip(draft.chosen, draft.quotes, strict=True)
    )
    try:
        await db.flush()
    except IntegrityError:  # the same key raced us: the other request's sale stands
        await db.rollback()
        replay = await _by_key(db, draft.user_id, key)
        if replay is None:
            raise
        return replay, False
    await db.commit()
    return sale, True


async def _apply(db: AsyncSession, sale_id: str, report: Deposit) -> Sale:
    locked = await lock_sale(db, sale_id)
    if locked is None:  # the row was committed above; only a bug gets here
        raise unavailable()
    await apply_deposit(db, locked, report, at=now())
    if report.amount_usd is not None and report.amount_usd < locked.quoted_usd:
        log.info(
            "sales.amount_below_quote",
            number=locked.number,
            quoted_usd=str(locked.quoted_usd),
            amount_usd=str(report.amount_usd),
        )
    await db.commit()
    return locked


async def _reload(db: AsyncSession, sale_id: str) -> Sale:
    sale = await db.get(Sale, sale_id, populate_existing=True)
    if sale is None:
        raise unavailable()
    return sale


async def _close(db: AsyncSession, sale_id: str, reason: str) -> None:
    """Close a sale Skinslink refused (no deposit exists), through the status module."""
    sale = await lock_sale(db, sale_id)
    if sale is not None:
        await close(db, sale, reason=reason)
    await db.commit()


async def _refused(
    db: AsyncSession,
    *,
    redis: Redis,
    client: DepositClient,
    sale_id: str,
    draft: _Draft,
    exc: SkinslinkError,
) -> Sale:
    if exc.status == 409 or exc.code == "already_exists":  # the call landed after all
        await check_sale(db, client, sale_id=sale_id)
        return await _reload(db, sale_id)
    code = exc.code or f"http_{exc.status}"
    await _close(db, sale_id, code)
    if code in PRICE_CODES:
        await forget_snapshot(redis, draft.user_id, draft.link.url)
        raise _prices_changed()
    if code in STEAM_ACCOUNT_CODES:
        raise ConflictError(
            "Steam does not let this account trade", code="steam_refused", reason=code
        )
    if code == "too_many_items":
        raise ConflictError(
            "too many items for one sale", code="too_many_items", max_items=draft.max_items
        )
    raise unavailable()


async def _deposit(
    db: AsyncSession, redis: Redis, client: DepositClient, sale_id: str, draft: _Draft
) -> Sale:
    """The one Skinslink call; its answer applied, or the sale closed or left for the poll."""
    try:
        report = await client.create_deposit(
            merchant_tx_id=sale_id,
            partner=draft.link.partner,
            token=draft.link.token,
            asset_ids=[i.id for i in draft.chosen],
            min_prices=min_prices([(i.id, i.price_usd) for i in draft.chosen]),
        )
    except SkinslinkForbiddenError:
        await _close(db, sale_id, "forbidden")
        raise unavailable() from None
    except SkinslinkError as exc:
        return await _refused(db, redis=redis, client=client, sale_id=sale_id, draft=draft, exc=exc)
    except SkinslinkUnavailableError as exc:
        log.warning("sales.deposit_unanswered", error=type(exc).__name__)
        return await _reload(db, sale_id)
    return await _apply(db, sale_id, report)


async def create_sale(
    db: AsyncSession,
    *,
    redis: Redis,
    user: User,
    body: SellIn,
    idempotency_key: str,
    client: DepositClient,
    settings: Settings,
) -> tuple[Sale, bool]:
    """Open a sale of the chosen items at the payout the cart showed.

    Returns:
        ``(sale, created)`` — ``created`` is ``False`` for a replayed key (the stored sale,
        whatever ``body`` says).

    Raises:
        ConflictError: ``sales_disabled``, ``trade_link_missing``, ``trade_link_bad``,
            ``prices_changed``, ``below_minimum``, ``below_card_minimum``, ``too_many_items``,
            ``steam_refused``, ``cards_limit``.
        ValidationError: ``card_invalid``.
        NotFoundError: A saved card that is not the seller's.
        RateUnavailableError: No fresh rate.
        SalesUnavailableError: Skinslink refused for a reason of ours, or answered 403.
    """
    existing = await _by_key(db, user.id, idempotency_key)
    if existing is not None:
        return existing, False
    draft = await _draft(db, redis, user, body, settings)
    sale, created = await _store(db, draft, idempotency_key)
    if not created:
        return sale, False
    log.info(
        "sales.created",
        number=sale.number,
        payout_to=draft.payout_to,
        items=len(draft.chosen),
        payout_uzs=str(draft.payout.payout_uzs),
    )
    return await _deposit(db, redis, client, sale.id, draft), True


__all__ = ["create_sale"]
