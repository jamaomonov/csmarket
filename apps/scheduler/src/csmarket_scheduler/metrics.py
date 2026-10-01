"""The scheduler's ``/metrics`` endpoint (ruling R14): the order-health gauges live here."""

from __future__ import annotations

from csmarket.core.config import get_settings
from csmarket.core.metrics import serve_metrics


def start_metrics_server() -> bool:
    """Serve ``/metrics`` on ``scheduler_metrics_port``; a taken port is logged, not fatal."""
    return serve_metrics(get_settings().scheduler_metrics_port, service="scheduler")


__all__ = ["start_metrics_server"]
