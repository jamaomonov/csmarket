"""Public interface of the ``admin`` module — other modules import from here only.

The router is mounted from ``api/v1/router.py`` (``admin.routes`` directly), like ``users``.
"""

from __future__ import annotations

from csmarket.modules.admin.audit import AuditPayload, record
from csmarket.modules.admin.deps import has_role, require_admin, required_key
from csmarket.modules.admin.users_service import remember, replayed

__all__ = [
    "AuditPayload",
    "has_role",
    "record",
    "remember",
    "replayed",
    "require_admin",
    "required_key",
]
