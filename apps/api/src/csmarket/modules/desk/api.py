"""What other modules may import from ``desk``: the webhook's hand-off and the poll."""

from __future__ import annotations

from csmarket.modules.desk.deposits import mark_due
from csmarket.modules.desk.models import DESK_TX_PREFIX
from csmarket.modules.desk.poll import poll_deposits

__all__ = ["DESK_TX_PREFIX", "mark_due", "poll_deposits"]
