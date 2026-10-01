"""Read a request body with a ceiling, for the kassa webhooks.

Starlette's ``request.body()`` buffers whatever the caller sends. The acquirer callbacks are
small JSON or form bodies, so each reads through :func:`read_capped` and answers its own
"malformed" code past the ceiling instead of holding an arbitrarily large body in memory.
"""

from __future__ import annotations

from fastapi import Request

#: The ceiling for Payme's and Uzum's JSON bodies: their calls are a few hundred bytes.
KASSA_JSON_MAX_BYTES = 64 * 1024


async def read_capped(request: Request, limit: int) -> bytes | None:
    """The body, or ``None`` once it grows past ``limit`` bytes (reading stops there).

    Args:
        request: The incoming request; its stream is consumed.
        limit: The largest body accepted, in bytes.

    Returns:
        The raw bytes, or ``None`` when the body is larger than ``limit``.
    """
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            return None
    return bytes(raw)


__all__ = ["KASSA_JSON_MAX_BYTES", "read_capped"]
