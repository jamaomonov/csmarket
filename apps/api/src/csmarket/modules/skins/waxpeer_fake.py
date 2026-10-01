"""A dev-only Waxpeer (ruling R13): trades in Redis, so local runs and e2e buy for nothing.

On with ``CSMARKET_WAXPEER_FAKE=true``; ``Settings`` refuses it in prod, and every factory
that picks it (:func:`csmarket.modules.skins.waxpeer_trades.trade_client`, the listings
client, the trade-link checker) checks :func:`fake_active` too.

A buy records a trade under ``skins:waxpeer:fake:trade:{project_id}`` — a hash of Waxpeer
trade id → the trade as Waxpeer's JSON spells it, kept 7 days. A second buy under the same
``project_id`` adds a second trade, as Waxpeer would, so a double buy shows. The offer goes
out by itself, derived from the clock on every read and never written back (a read can then
never undo a dev action): status 0, then 2 with a 10-digit ``trade_id`` after
:data:`SENDING_AFTER`, then 4 with ``send_until`` 30 minutes after the offer went out
(:data:`SENT_AFTER`). The dev routes drive the rest (:meth:`FakeTradeClient.act`):
``accept`` (``release_date`` in 7 days), ``decline`` (6, "Buyer failed to accept"),
``rollback`` (6 with penalties, after an accept). A buy never fails.

Neither the trade link nor the buyer's Steam ID is stored. A Redis failure reads as a
Waxpeer outage (``WaxpeerUnavailableError``), which every caller already treats as
"unknown, resolve by lookup".
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.skins.waxpeer import WaxpeerUnavailableError
from csmarket.modules.skins.waxpeer_trades import (
    LOOKUP_MAX_IDS,
    WaxpeerBuy,
    WaxpeerTrade,
    parse_trade,
)

log = get_logger("csmarket.skins.waxpeer_fake")

TRADE_KEY = "skins:waxpeer:fake:trade:{}"
BALANCE_KEY = "skins:waxpeer:fake:balance"
TRADE_TTL_SECONDS = 7 * 86_400
#: Our Waxpeer balance until the dev route sets one: $10 000 (1000 units = $1).
DEFAULT_BALANCE_UNITS = 10_000_000
#: From the buy to the seller sending (status 2) and to the offer being out (status 4).
SENDING_AFTER = timedelta(seconds=3)
SENT_AFTER = timedelta(seconds=6)
#: How long the buyer has to accept an offer.
OFFER_WINDOW = timedelta(minutes=30)
#: Steam's trade protection after an accept.
PROTECTION = timedelta(days=7)
DECLINE_REASON = "Buyer failed to accept"

FakeAction = Literal["accept", "decline", "rollback"]

_UNACCEPTED = (0, 2, 4)


def fake_active(settings: Settings) -> bool:
    """The fake is on: flagged, and never in prod (a copied ``Settings`` skips its validator)."""
    return settings.waxpeer_fake and not settings.is_prod


def _sent_view(doc: dict[str, Any]) -> dict[str, Any]:  # Any: Waxpeer-shaped trade JSON
    """``doc`` as Waxpeer would report it now: a fresh buy moves on with the clock."""
    if doc.get("status") != 0:
        return doc
    created = datetime.fromtimestamp(float(doc["created_at"]), tz=UTC)
    elapsed = clock.now() - created
    if elapsed < SENDING_AFTER:
        return doc
    # Waxpeer's Steam offer id: 10 digits, the same on every read.
    view = {**doc, "status": 2, "trade_id": f"7{int(doc['id']) % 1_000_000_000:09d}"}
    if elapsed >= SENT_AFTER:
        until = created + SENT_AFTER + OFFER_WINDOW
        view.update(status=4, send_until=str(int(until.timestamp())))
    return view


class FakeTradeClient:
    """A :class:`~csmarket.modules.skins.waxpeer_trades.TradeClient`, a listings search
    client and a trade-link checker backed by Redis; see the module docstring."""

    def __init__(self, redis: Redis) -> None:
        """Keep the trades in ``redis``."""
        self._redis = redis

    async def buy_one_p2p(
        self, *, item_id: int, price_units: int, partner: int, token: str, project_id: str
    ) -> WaxpeerBuy:
        """Record a new trade at status 0 under ``project_id``; it always goes through.

        ``partner`` and ``token`` are not kept: the fake sends nothing to Steam.

        Raises:
            WaxpeerUnavailableError: Redis failed (the buy may or may not be recorded).
        """
        del partner, token
        trade_id = 100_000_000 + secrets.randbelow(900_000_000)
        doc: dict[str, Any] = {  # Any: Waxpeer-shaped trade JSON
            "id": trade_id,
            "project_id": project_id,
            "item_id": item_id,
            "price": price_units,
            "status": 0,
            "trade_id": None,
            "done": False,
            "reason": None,
            "release_date": None,
            "is_released": False,
            "send_until": None,
            "penalties": None,
            "escrow_status": None,
            "seller_name": "fake_seller",
            "seller_steam_level": 10,
            "created_at": clock.now().timestamp(),
        }
        key = TRADE_KEY.format(project_id)
        try:
            await self._redis.hset(key, str(trade_id), json.dumps(doc))
            await self._redis.expire(key, TRADE_TTL_SECONDS)
        except RedisError as exc:
            raise WaxpeerUnavailableError("fake: redis") from exc
        log.info("skins.waxpeer_fake.bought", project_id=project_id, waxpeer_id=trade_id)
        return WaxpeerBuy(id=trade_id, price_units=price_units)

    async def _docs(self, project_id: str) -> list[dict[str, Any]]:  # Any: trade JSON
        """The stored trades of ``project_id`` as Waxpeer reports them now, oldest first."""
        try:
            raw = await self._redis.hgetall(TRADE_KEY.format(project_id))
        except RedisError as exc:
            raise WaxpeerUnavailableError("fake: redis") from exc
        try:
            docs = [json.loads(value) for value in raw.values()]
            docs.sort(key=lambda doc: (float(doc["created_at"]), int(doc["id"])))
            return [_sent_view(doc) for doc in docs]
        except (KeyError, TypeError, ValueError) as exc:
            # Not a trade this fake wrote: unreadable, as a garbled Waxpeer answer.
            raise WaxpeerUnavailableError("fake: unreadable trade") from exc

    async def check_project_ids(self, project_ids: Sequence[str]) -> list[WaxpeerTrade]:
        """The stored trades of up to 100 ``project_id`` values; unknown ids are absent.

        Raises:
            ValueError: More than :data:`LOOKUP_MAX_IDS` ids (as the real client).
            TypeError: One bare string instead of a sequence of ids.
            WaxpeerUnavailableError: Redis failed or a stored trade is unreadable.
        """
        if isinstance(project_ids, str):
            raise TypeError("project_ids must be a sequence of ids, not one string")
        if len(project_ids) > LOOKUP_MAX_IDS:
            raise ValueError(f"at most {LOOKUP_MAX_IDS} project ids per lookup")
        trades: list[WaxpeerTrade] = []
        for project_id in dict.fromkeys(project_ids):
            trades.extend(parse_trade(doc) for doc in await self._docs(project_id))
        return trades

    async def balance_units(self) -> int:
        """The fake balance (1000 = $1); :data:`DEFAULT_BALANCE_UNITS` until set.

        Raises:
            WaxpeerUnavailableError: Redis failed or holds something that is not a number.
        """
        try:
            raw = await self._redis.get(BALANCE_KEY)
            return int(raw or DEFAULT_BALANCE_UNITS)
        except (RedisError, ValueError) as exc:
            raise WaxpeerUnavailableError("fake: balance") from exc

    async def set_balance(self, units: int) -> None:
        """Set the fake balance (the dev route; no TTL)."""
        await self._redis.set(BALANCE_KEY, str(units))

    async def search_listings(
        self, names: Sequence[str], *, game: str = "csgo"
    ) -> dict[str, list[dict[str, Any]]]:  # Any: Waxpeer listing JSON
        """No live listings: always an outage, so item pages serve the seeded snapshot.

        Raises:
            WaxpeerUnavailableError: Always.
        """
        del names, game
        raise WaxpeerUnavailableError("fake: no live listings")

    async def check_tradelink(self, url: str) -> str | None:
        """Every trade link works (``None``)."""
        del url
        return None

    async def act(
        self, project_id: str, action: FakeAction, *, waxpeer_id: int | None
    ) -> WaxpeerTrade:
        """Accept, decline or roll back a trade of ``project_id``; a repeat is a no-op.

        Acts on the trade ``waxpeer_id`` when we recorded one, else on the newest.

        Raises:
            ConflictError: ``fake_trade_missing`` (nothing bought yet) or
                ``fake_trade_state`` (e.g. accept before the offer is out).
        """
        docs = await self._docs(project_id)
        doc = next((d for d in docs if int(d["id"]) == waxpeer_id), None) if waxpeer_id else None
        doc = doc or (docs[-1] if docs else None)
        if doc is None:
            raise ConflictError("no fake trade for this order", code="fake_trade_missing")
        moved = _moved(doc, action)
        if moved is not doc:
            key = TRADE_KEY.format(project_id)
            await self._redis.hset(key, str(doc["id"]), json.dumps(moved))
            log.info("skins.waxpeer_fake.acted", project_id=project_id, action=action)
        return parse_trade(moved)


def _moved(doc: dict[str, Any], action: FakeAction) -> dict[str, Any]:  # Any: trade JSON
    """``doc`` after ``action`` (``doc`` itself when already done).

    Raises:
        ConflictError: ``fake_trade_state`` — the action does not fit the trade's state.
    """
    status, accepted = doc["status"], doc.get("release_date") is not None
    now = clock.now()
    if action == "accept":
        if status == 4 and accepted:
            return doc
        if status == 4:
            return {**doc, "release_date": (now + PROTECTION).isoformat()}
    elif action == "decline":
        if status == 6 and not doc.get("penalties"):
            return doc
        if status in _UNACCEPTED and not accepted:
            return {**doc, "status": 6, "reason": DECLINE_REASON, "done": True}
    else:
        if status == 6 and doc.get("penalties"):
            return doc
        if status == 4 and accepted:
            return {**doc, "status": 6, "done": True, "penalties": {"rollback_fee": doc["price"]}}
    raise ConflictError(f"cannot {action} a fake trade at status {status}", code="fake_trade_state")


def fake_client() -> FakeTradeClient:
    """The fake on the process Redis — a FastAPI dependency of the dev routes.

    Raises:
        NotFoundError: The fake is off: the dev routes do not exist then.
    """
    if not fake_active(get_settings()):
        raise NotFoundError("not found")
    return FakeTradeClient(get_redis())


__all__ = [
    "BALANCE_KEY",
    "DEFAULT_BALANCE_UNITS",
    "TRADE_KEY",
    "FakeAction",
    "FakeTradeClient",
    "fake_active",
    "fake_client",
]
