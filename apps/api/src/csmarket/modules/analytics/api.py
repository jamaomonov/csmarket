"""Public interface of the ``analytics`` module — other modules import from here only.

The router is mounted from ``api/v1/router.py`` (``analytics.routes`` directly).
"""

from __future__ import annotations

from csmarket.modules.analytics.window import Channel, Window, month_window, parse_window

__all__ = ["Channel", "Window", "month_window", "parse_window"]
