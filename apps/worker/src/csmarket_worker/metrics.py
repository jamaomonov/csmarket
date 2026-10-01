"""The worker's ``/metrics`` endpoint (ruling R14): the buy counters live here."""

from __future__ import annotations

from csmarket.core.config import get_settings
from csmarket.core.metrics import serve_metrics


def start_metrics_server() -> bool:
    """Serve ``/metrics`` on ``worker_metrics_port``; a taken port is logged, not fatal."""
    return serve_metrics(get_settings().worker_metrics_port, service="worker")


__all__ = ["start_metrics_server"]
