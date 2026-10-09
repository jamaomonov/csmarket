"""Public interface of the ``users`` module — other modules import from here only.

The ``/me`` router is not re-exported here: ``auth`` imports this module for ``User`` and
the upsert, and ``users.routes`` imports ``auth.api`` for ``current_user`` — re-exporting
the router would close that cycle. ``api/v1/router.py`` mounts ``users.routes.router``.
"""

from __future__ import annotations

from csmarket.modules.users.models import User
from csmarket.modules.users.service import (
    STEAM64_BASE,
    get_user_by_id,
    get_user_by_steam_id,
    set_roles,
    upsert_user_by_steam,
)
from csmarket.modules.users.tradelink import (
    CheckResult,
    HoldChecker,
    TradeLink,
    TradelinkChecker,
    check_trade_link,
    mask_trade_link,
    parse_tradelink,
)
from csmarket.modules.users.tradelink_checkers import tradelink_checkers

__all__ = [
    "STEAM64_BASE",
    "CheckResult",
    "HoldChecker",
    "TradeLink",
    "TradelinkChecker",
    "User",
    "check_trade_link",
    "get_user_by_id",
    "get_user_by_steam_id",
    "mask_trade_link",
    "parse_tradelink",
    "set_roles",
    "tradelink_checkers",
    "upsert_user_by_steam",
]
