"""Domain event base.

Cross-module communication in production goes through Postgres (the ``orders`` table is
the queue, spec §5) and Redis pub/sub (``realtime``, M4); this type is the shared envelope.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from csmarket.core.clock import now
from csmarket.core.ids import new_id


class DomainEvent(BaseModel):
    """Base class for all domain events. Immutable, serialisable, identified."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(default_factory=new_id)
    occurred_at: str = Field(default_factory=lambda: now().isoformat())
    type: str
    aggregate: str
    aggregate_id: str
    payload: dict[str, Any]


EventHandler = Callable[[DomainEvent], Awaitable[None]]
