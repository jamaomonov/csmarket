"""Public interface of ``reviews`` — what other modules import (the admin dashboard, the
scheduler). The routers are mounted from ``api/v1/router.py``."""

from __future__ import annotations

from csmarket.modules.reviews.admin import bad_open_count

__all__ = ["bad_open_count"]
