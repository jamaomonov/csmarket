"""``/api/v1`` — public API mount.

Modules register their routers here. Keep the imports alphabetical for diff
readability. Empty in M0; M1 mounts ``auth`` and ``users``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
