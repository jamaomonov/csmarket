"""The customer's Steam trade link: parse, prove ownership, advisory check (spec §7.2).

The ``token`` in a trade link lets anyone send that account offers — a credential. It is
never logged and never part of a Redis key (keys use a SHA-256 digest of the link).
The check asks Waxpeer whether the link works (private inventory, trade ban) and Steam
whether a trade would be held (no mobile authenticator → escrow). It is advisory: any
upstream failure answers ``unavailable`` and opens a 60-second breaker (AGENTS §11).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core.errors import ValidationError
from csmarket.core.logging import get_logger
from csmarket.modules.users.service import STEAM64_BASE

log = get_logger("csmarket.users.tradelink")

#: ``re.ASCII``: in a Unicode pattern ``\d`` matches Arabic-Indic or full-width digits
#: (which ``int()`` then accepts) and ``\w`` matches Cyrillic — look-alike links.
_LINK = re.compile(
    r"^https://steamcommunity\.com/tradeoffer/new/\?partner=(\d{1,12})&token=([\w-]{6,16})$",
    re.ASCII,
)
CACHE_TTL_SECONDS = 600
BREAKER_TTL_SECONDS = 60
_CACHE_PREFIX = "users:tradelink:"
BREAKER_KEY = "users:tradelink:breaker"

Verdict = Literal["ok", "warn", "bad"]
Reason = Literal["invalid", "private", "trade_ban", "hold", "unavailable"]


@dataclass(frozen=True, slots=True)
class TradeLink:
    """A parsed trade link."""

    url: str
    partner: int
    token: str

    @property
    def steam_id(self) -> str:
        """The account's steamid64, as ``users.steam_id`` stores it."""
        return str(self.partner + STEAM64_BASE)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """``verdict`` is ``None`` only when the check could not run (``reason="unavailable"``)."""

    verdict: Verdict | None
    reason: Reason | None


class TradelinkChecker(Protocol):
    """Waxpeer's ``check-tradelink``: ``None`` when fine, else a reason text."""

    async def check_tradelink(self, url: str) -> str | None:
        """Waxpeer's reason for ``url``, or ``None``."""
        ...


class HoldChecker(Protocol):
    """Steam ``GetTradeHoldDurations``: days a trade would be held; ``None`` = no number."""

    async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
        """Hold in days."""
        ...


def parse_tradelink(raw: str) -> TradeLink:
    """Parse Steam's «Trade URL».

    Raises:
        ValidationError: ``code="trade_link_invalid"`` for anything but that exact link.
    """
    url = raw.strip()
    match = _LINK.match(url)
    if match is None:
        raise ValidationError("not a Steam trade link", code="trade_link_invalid")
    return TradeLink(url=url, partner=int(match.group(1)), token=match.group(2))


#: What stands in for the hidden part of a trade-link token.
MASK = "••••"


def mask_trade_link(raw: str | None) -> str | None:
    """The link with its token hidden but for the last 2 characters — for admin views.

    ``partner`` stays (an operator matches it to the Steam account); the token is a
    credential and never leaves whole. A stored value that is not a trade link (none
    should be: ``save_trade_link`` parses first) is masked entirely.

    Examples:
        >>> mask_trade_link("https://steamcommunity.com/tradeoffer/new/?partner=1&token=AbCdEf12")
        'https://steamcommunity.com/tradeoffer/new/?partner=1&token=••••12'
    """
    if raw is None:
        return None
    match = _LINK.match(raw.strip())
    if match is None:
        return MASK
    partner, token = match.group(1), match.group(2)
    return f"https://steamcommunity.com/tradeoffer/new/?partner={partner}&token={MASK}{token[-2:]}"


def assert_owned(link: TradeLink, steam_id: str) -> None:
    """The link must belong to the signed-in account (spec §7.2).

    Raises:
        ValidationError: ``code="trade_link_not_yours"``.
    """
    if link.steam_id != steam_id:
        raise ValidationError(
            "this trade link belongs to another Steam account", code="trade_link_not_yours"
        )


def _reason_for(info: str) -> Reason:
    text = info.lower()
    if "private" in text:
        return "private"
    if "ban" in text:
        return "trade_ban"
    return "invalid"


def _cache_key(link: TradeLink) -> str:
    return _CACHE_PREFIX + hashlib.sha256(link.url.encode()).hexdigest()[:32]


async def _run(link: TradeLink, *, waxpeer: TradelinkChecker, hold: HoldChecker) -> CheckResult:
    info = await waxpeer.check_tradelink(link.url)
    if info:
        return CheckResult(verdict="bad", reason=_reason_for(info))
    days = await hold.trade_hold_days(link.steam_id, link.token)
    if days:
        return CheckResult(verdict="warn", reason="hold")
    return CheckResult(verdict="ok", reason=None)


async def check_trade_link(
    link: TradeLink, *, waxpeer: TradelinkChecker, hold: HoldChecker, redis: Redis
) -> CheckResult:
    """The advisory check: 10-minute cache per link, 60-second breaker on any failure."""
    unavailable = CheckResult(verdict=None, reason="unavailable")
    key = _cache_key(link)
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError):
        cached = await redis.get(key)
        if cached is not None:
            data = json.loads(cached)
            return CheckResult(verdict=data["verdict"], reason=data["reason"])
    with contextlib.suppress(RedisError):
        if await redis.exists(BREAKER_KEY):
            return unavailable
    try:
        result = await _run(link, waxpeer=waxpeer, hold=hold)
    except Exception as exc:  # noqa: BLE001 -- advisory: every upstream failure is "unavailable"
        # The type name only: an httpx message carries the URL, key and token included.
        log.warning("users.tradelink.unavailable", error=type(exc).__name__)
        with contextlib.suppress(RedisError):
            await redis.set(BREAKER_KEY, "1", ex=BREAKER_TTL_SECONDS)
        return unavailable
    with contextlib.suppress(RedisError):
        await redis.set(
            key,
            json.dumps({"verdict": result.verdict, "reason": result.reason}),
            ex=CACHE_TTL_SECONDS,
        )
    log.info("users.tradelink.checked", verdict=result.verdict, reason=result.reason)
    return result


__all__ = [
    "BREAKER_KEY",
    "BREAKER_TTL_SECONDS",
    "CACHE_TTL_SECONDS",
    "CheckResult",
    "HoldChecker",
    "Reason",
    "TradeLink",
    "TradelinkChecker",
    "Verdict",
    "assert_owned",
    "check_trade_link",
    "parse_tradelink",
]
