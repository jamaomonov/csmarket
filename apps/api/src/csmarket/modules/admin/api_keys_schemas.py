"""Wire shapes for ``/api/v1/admin/api-keys`` (the admin SPA's API-keys page).

Money is USD with three decimals as a string. The key's token is never shown (only its hash
is stored); the webhook is named by its host, never the full URL (a URL can carry a secret).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from csmarket.modules.admin.orders_schemas import AdminOrderRow, AdminOrderUser
from csmarket.modules.admin.users_schemas import Reason

Tariff = Literal["retail", "cost"]


class AdminApiKeyRow(BaseModel):
    """One key with what it has sold."""

    id: str
    user: AdminOrderUser
    pricing_profile: Tariff
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    #: Orders placed through the key.
    orders: int
    #: Sum of ``price_usd`` of the key's orders that were not refunded.
    revenue_usd: str
    #: Sum of ``cost_usd`` of the key's orders.
    cost_usd: str


class AdminApiKeysOut(BaseModel):
    """A page of keys (live first, newest first) and the next cursor."""

    items: list[AdminApiKeyRow]
    next_cursor: str | None


class AdminApiKeyDelivery(BaseModel):
    """The newest webhook delivery of the key's owner."""

    event: str
    status: Literal["pending", "sent", "failed"]
    attempts: int
    last_status_code: int | None
    created_at: datetime


class AdminApiKeyWebhook(BaseModel):
    """The owner's webhook: host only."""

    host: str
    last_delivery: AdminApiKeyDelivery | None


class AdminApiKeyCard(BaseModel):
    """The key page: the row, the latest 20 orders and the webhook."""

    key: AdminApiKeyRow
    orders: list[AdminOrderRow]
    webhook: AdminApiKeyWebhook | None


class AdminTariffIn(BaseModel):
    """Switch the tariff, with a reason."""

    model_config = ConfigDict(extra="forbid")

    pricing_profile: Tariff
    reason: Reason


class AdminRevokeKeyIn(BaseModel):
    """Revoke a key, with a reason."""

    model_config = ConfigDict(extra="forbid")

    reason: Reason


__all__ = [
    "AdminApiKeyCard",
    "AdminApiKeyDelivery",
    "AdminApiKeyRow",
    "AdminApiKeyWebhook",
    "AdminApiKeysOut",
    "AdminRevokeKeyIn",
    "AdminTariffIn",
]
