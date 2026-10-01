"""The worker serves ``/metrics``, and a taken port never stops it."""

from __future__ import annotations

import socket
import urllib.request

import pytest
from csmarket.core.config import get_settings
from csmarket.core.metrics import set_orders_stuck
from csmarket_worker import metrics


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def _serve_on(monkeypatch: pytest.MonkeyPatch, port: int) -> bool:
    settings = get_settings().model_copy(update={"worker_metrics_port": port})
    monkeypatch.setattr(metrics, "get_settings", lambda: settings)
    return metrics.start_metrics_server()


def test_the_metrics_endpoint_serves_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    set_orders_stuck("paid", 3)
    assert _serve_on(monkeypatch, port)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as resp:
        body = resp.read().decode()
    assert 'csmarket_orders_stuck{state="paid"} 3.0' in body
    assert 'csmarket_order_buys_total{outcome="bought"}' in body  # pre-created at 0


def test_a_taken_port_is_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as taken:
        taken.bind(("0.0.0.0", 0))
        taken.listen()
        assert _serve_on(monkeypatch, taken.getsockname()[1]) is False


def test_the_default_ports_are_the_documented_ones() -> None:
    settings = get_settings()
    assert (settings.worker_metrics_port, settings.scheduler_metrics_port) == (9101, 9102)
