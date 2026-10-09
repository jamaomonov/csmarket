"""The production trade-link checkers (Waxpeer ``check-tradelink`` + Steam hold), shared by
the site's ``/me`` check and the public API's ``/public/tradelink/check``."""

from __future__ import annotations

from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.skins.api import FakeTradeClient, WaxpeerClient, fake_active
from csmarket.modules.users.tradelink import HoldChecker, TradelinkChecker

_ADVISORY_TIMEOUT = 4.0


class _SteamHold:
    """Steam's hold check with our key; no key → no number (ruling P10)."""

    async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
        """Days Steam would hold a trade to this link, or ``None`` without a key."""
        # Imported here: ``auth.api`` imports ``users.api``, which re-exports this module.
        from csmarket.modules.auth.api import trade_hold_days

        key = get_settings().steam_api_key
        if not key:
            return None
        return await trade_hold_days(int(steam_id), token, api_key=key)


def tradelink_checkers() -> tuple[TradelinkChecker, HoldChecker]:
    """Upstream checkers; overridden in tests via ``app.dependency_overrides``.

    Under the dev Waxpeer fake every link passes Waxpeer's half of the check.
    """
    s = get_settings()
    if fake_active(s):
        return FakeTradeClient(get_redis()), _SteamHold()
    waxpeer = WaxpeerClient(
        api_key=s.waxpeer_api_key, base_url=s.waxpeer_base_url, timeout_seconds=_ADVISORY_TIMEOUT
    )
    return waxpeer, _SteamHold()
