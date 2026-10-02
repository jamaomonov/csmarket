"""Public interface of the ``auth`` module — other modules import from here only."""

from __future__ import annotations

from csmarket.modules.auth.deps import current_user
from csmarket.modules.auth.ip_guard import guard_ip
from csmarket.modules.auth.routes import router
from csmarket.modules.auth.schemas import TokensOut
from csmarket.modules.auth.service import (
    AuthenticatedUser,
    SessionTokens,
    authenticate,
    revoke_all_sessions,
)
from csmarket.modules.auth.steam import trade_hold_days

__all__ = [
    "AuthenticatedUser",
    "SessionTokens",
    "TokensOut",
    "authenticate",
    "current_user",
    "guard_ip",
    "revoke_all_sessions",
    "router",
    "trade_hold_days",
]
