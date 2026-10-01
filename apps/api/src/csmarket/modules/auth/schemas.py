"""Pydantic DTOs for the ``auth`` HTTP surface."""

from __future__ import annotations

from pydantic import BaseModel


class TokensOut(BaseModel):
    """Response for any endpoint that opens or rotates a session.

    The refresh token is intentionally absent: it is delivered as an ``HttpOnly`` cookie
    (see :mod:`csmarket.modules.auth.cookies`) so JS cannot read it. Only the short-lived
    access token — which the app attaches as a Bearer header — is returned in the body.
    """

    access_token: str
    token_type: str = "Bearer"  # noqa: S105 -- OAuth token-type literal, not a credential
    expires_in: int


__all__ = ["TokensOut"]
