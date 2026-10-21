"""Admin wire models for kassa limits and a user's risk policy."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Kassa = Literal["payme", "click", "uzum", "p2p"]
Amount = Annotated[int, Field(ge=1, le=1_000_000_000)]
Window = Annotated[int, Field(ge=1, le=720)]


class AuthorOut(BaseModel):
    """Who saved."""

    id: str
    display_name: str | None


class KassaLimitIn(BaseModel):
    """One kassa's limit as the admin saves it."""

    model_config = ConfigDict(extra="forbid")

    provider: Kassa
    enabled: bool
    max_amount_uzs: Amount
    window_hours: Window


class ReviewLimitsIn(BaseModel):
    """The kassas to save; one row per kassa at most."""

    model_config = ConfigDict(extra="forbid")

    limits: Annotated[list[KassaLimitIn], Field(min_length=1, max_length=4)]

    @model_validator(mode="after")
    def _unique(self) -> ReviewLimitsIn:
        names = [x.provider for x in self.limits]
        if len(names) != len(set(names)):
            raise ValueError("each kassa at most once")
        return self


class KassaLimitOut(BaseModel):
    """One kassa's limit."""

    provider: str
    enabled: bool
    max_amount_uzs: str
    window_hours: int


class ReviewLimitsOut(BaseModel):
    """Every kassa's limit; ``updated_at`` is the version for ``If-Match``."""

    limits: list[KassaLimitOut]
    updated_at: datetime | None
    updated_by: AuthorOut | None


class RiskPolicyIn(BaseModel):
    """A user's policy as the admin saves it."""

    model_config = ConfigDict(extra="forbid")

    trusted: bool
    kassa_blocked: bool
    max_amount_uzs: Amount | None
    window_hours: Window = 24
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class RiskPolicyOut(BaseModel):
    """A user's policy and their recent kassa money, for the user card."""

    trusted: bool
    kassa_blocked: bool
    max_amount_uzs: str | None
    window_hours: int
    note: str | None
    updated_at: datetime | None
    updated_by: AuthorOut | None
    money_in_24h_uzs: str
    money_in_7d_uzs: str
    open_holds: int
