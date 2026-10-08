"""Pydantic shapes of the site's API-key routes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ApiKeyOut(BaseModel):
    """The live key's public facts (never the token)."""

    model_config = ConfigDict(frozen=True)

    id: str
    pricing_profile: str
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyIssuedOut(BaseModel):
    """A freshly issued key: the token is shown this once."""

    model_config = ConfigDict(frozen=True)

    id: str
    token: str
    pricing_profile: str
    created_at: datetime


__all__ = ["ApiKeyIssuedOut", "ApiKeyOut"]
