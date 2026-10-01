"""``/api/v1`` — public API mount.

Modules register their routers here (not in the package ``__init__``, which
``api/v1/deps.py`` importers run first — see ``tests/unit/test_import_order.py``).
Keep the imports alphabetical for diff readability.
"""

from __future__ import annotations

from fastapi import APIRouter

from csmarket.modules.auth.api import router as auth_router

router = APIRouter()
router.include_router(auth_router)
