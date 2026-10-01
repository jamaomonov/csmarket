"""``/api/v1`` — public API mount.

Modules register their routers here (not in the package ``__init__``, which
``api/v1/deps.py`` importers run first — see ``tests/unit/test_import_order.py``).
Keep the imports alphabetical for diff readability. A module whose routes import
``auth.api`` while ``auth`` imports its ``api`` (``users``) is mounted from its
``routes`` module directly — see ``modules/users/api.py`` (``admin`` likewise).
"""

from __future__ import annotations

from fastapi import APIRouter

from csmarket.modules.admin.routes import router as admin_router
from csmarket.modules.auth.api import router as auth_router
from csmarket.modules.users.routes import router as users_router

router = APIRouter()
router.include_router(admin_router)
router.include_router(auth_router)
router.include_router(users_router)
