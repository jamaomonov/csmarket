"""Public interface of the ``skins`` module — other modules import from here only."""

from __future__ import annotations

from csmarket.modules.skins.waxpeer import (
    SnapshotRow,
    WaxpeerClient,
    WaxpeerError,
    WaxpeerRateLimitedError,
    WaxpeerUnavailableError,
)

__all__ = [
    "SnapshotRow",
    "WaxpeerClient",
    "WaxpeerError",
    "WaxpeerRateLimitedError",
    "WaxpeerUnavailableError",
]
