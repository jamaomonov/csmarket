"""Wire shapes of the admin «P2P» pages (spec 2026-10-19-p2p-topup). A card's number never
leaves masked here; soʻm are digit strings."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Network = Literal["humo", "uzcard"]


class CardIn(BaseModel):
    """A new card: the full number once."""

    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, Field(min_length=1, max_length=64)]
    pan: Annotated[str, Field(min_length=16, max_length=32)]
    holder_name: Annotated[str, Field(min_length=1, max_length=128)]
    network: Network = "humo"
    min_amount_uzs: Annotated[int, Field(strict=True, ge=1000)] = 10_000
    max_amount_uzs: Annotated[int, Field(strict=True, ge=1000)] = 5_000_000
    daily_limit_uzs: Annotated[int | None, Field(strict=True, ge=1000)] = None


class CardPatch(BaseModel):
    """Change a card: on / off and its limits."""

    model_config = ConfigDict(extra="forbid")

    active: bool | None = None
    label: Annotated[str | None, Field(min_length=1, max_length=64)] = None
    min_amount_uzs: Annotated[int | None, Field(strict=True, ge=1000)] = None
    max_amount_uzs: Annotated[int | None, Field(strict=True, ge=1000)] = None
    daily_limit_uzs: Annotated[int | None, Field(strict=True, ge=1000)] = None
    #: ``daily_limit_uzs`` is cleared (no limit) when true.
    no_daily_limit: bool = False


class CardOut(BaseModel):
    """A card as the admin sees it: masked."""

    id: str
    label: str
    masked: str
    holder_name: str
    network: Network
    active: bool
    min_amount_uzs: str
    max_amount_uzs: str
    daily_limit_uzs: str | None
    #: Received today (Tashkent): paid requests plus open holds.
    today_uzs: str
    created_at: datetime


class CardsOut(BaseModel):
    """Every card, newest first."""

    items: list[CardOut]


class IncomingOut(BaseModel):
    """One HUMO notification and what it turned into."""

    id: str
    kind: Literal["credit", "debit", "unparsed"]
    amount_uzs: str | None
    card_last4: str | None
    source_text: str | None
    bank_time: datetime | None
    balance_after: str | None
    chain_ok: bool | None
    result: Literal["matched", "unmatched", "ignored"]
    #: The request it paid, or the top-up a manual credit opened.
    number: str | None
    received_at: datetime
    #: An unmatched credit an admin may book for a user now.
    can_credit: bool


class IncomingPage(BaseModel):
    """A page of the journal, newest first."""

    items: list[IncomingOut]
    next_cursor: str | None


class RequestUser(BaseModel):
    """Who asked for the transfer."""

    id: str
    display_name: str | None
    avatar_url: str | None


class RequestOut(BaseModel):
    """One top-up request."""

    number: str
    status: Literal["pending", "paid", "expired", "cancelled"]
    amount_uzs: str
    card_masked: str
    user: RequestUser
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None


class RequestsPage(BaseModel):
    """A page of requests, newest first."""

    items: list[RequestOut]
    next_cursor: str | None


class SettingsIn(BaseModel):
    """The trusted Telegram ids and the buyer's limits."""

    model_config = ConfigDict(extra="forbid")

    humo_bot_user_id: Annotated[int | None, Field(strict=True, gt=0)] = None
    owner_telegram_user_id: Annotated[int | None, Field(strict=True, gt=0)] = None
    min_amount_uzs: Annotated[int, Field(strict=True, ge=1000)]
    max_amount_uzs: Annotated[int, Field(strict=True, ge=1000)]
    daily_count: Annotated[int, Field(strict=True, ge=1, le=100)]
    daily_amount_uzs: Annotated[int, Field(strict=True, ge=1000)]


class SettingsOut(SettingsIn):
    """The settings and the connection's state."""

    model_config = ConfigDict(extra="ignore")

    connected: bool
    last_received_at: datetime | None
    updated_at: datetime


class CreditIn(BaseModel):
    """Book an unmatched transfer for a user."""

    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[str, Field(min_length=36, max_length=36)]
    note: Annotated[str, Field(min_length=4, max_length=300)]


class CreditOut(BaseModel):
    """The booked transfer."""

    incoming: IncomingOut
    topup_number: str
