"""Pydantic DTOs for the ``auth`` HTTP surface."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TokensOut(BaseModel):
    """Response for any endpoint that opens or rotates a session.

    The refresh token is intentionally absent: it is delivered as an ``HttpOnly`` cookie
    (see :mod:`csmarket.modules.auth.cookies`) so JS cannot read it. Only the short-lived
    access token — which the app attaches as a Bearer header — is returned in the body.
    """

    access_token: str
    token_type: str = "Bearer"  # noqa: S105 -- OAuth token-type literal, not a credential
    expires_in: int


class SteamCallbackIn(BaseModel):
    """The ``openid.*`` params exactly as Steam appended them, and which app asked."""

    model_config = ConfigDict(extra="forbid")

    app: Literal["web", "admin"]
    params: dict[str, str] = Field(min_length=4, max_length=32)


class DevLoginIn(BaseModel):
    """Dev/e2e sign-in (ruling P6)."""

    model_config = ConfigDict(extra="forbid")

    steam_id: str = Field(pattern=r"^7656119\d{10}$")
    display_name: str | None = Field(default=None, max_length=64)
    admin: bool = False


__all__ = ["DevLoginIn", "SteamCallbackIn", "TokensOut"]
