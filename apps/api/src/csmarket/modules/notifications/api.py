"""The ``notifications`` interface other modules import (M4b).

``orders`` and ``users`` enqueue letters with :func:`enqueue` inside their own
transactions; the worker drains them with :func:`drain_emails` on :data:`EMAILS_CHANNEL`.
Nothing here imports ``orders`` or ``payments`` at import time.
"""

from __future__ import annotations

from csmarket.modules.notifications.outbox import EMAILS_CHANNEL, enqueue
from csmarket.modules.notifications.sender import drain_emails

__all__ = ["EMAILS_CHANNEL", "drain_emails", "enqueue"]
