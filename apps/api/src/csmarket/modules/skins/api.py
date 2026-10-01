"""Public interface of the ``skins`` module — other modules import from here only."""

from __future__ import annotations

from csmarket.modules.skins.waxpeer import WaxpeerClient, WaxpeerError, WaxpeerUnavailableError

__all__ = ["WaxpeerClient", "WaxpeerError", "WaxpeerUnavailableError"]
