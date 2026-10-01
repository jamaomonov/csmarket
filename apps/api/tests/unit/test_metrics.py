"""Domain counters never fail a request and carry only closed label sets."""

from __future__ import annotations

from typing import Any

import pytest
from csmarket.core import metrics
from csmarket.core.metrics import STEAM_WEB_API_CALLS, record_steam_web_api_call, steam_web_api_call


def _value(**labels: str) -> float:
    return STEAM_WEB_API_CALLS.labels(**labels)._value.get()  # type: ignore[no-any-return]


def test_record_increments_the_labelled_series() -> None:
    before = _value(endpoint="get_player_summaries", consumer="auth_signin", outcome="ok")
    record_steam_web_api_call(endpoint="get_player_summaries", consumer="auth_signin", outcome="ok")
    assert (
        _value(endpoint="get_player_summaries", consumer="auth_signin", outcome="ok") == before + 1
    )


def test_context_manager_counts_ok_and_error() -> None:
    ok_before = _value(endpoint="get_trade_hold_durations", consumer="trade_link", outcome="ok")
    err_before = _value(endpoint="get_trade_hold_durations", consumer="trade_link", outcome="error")
    with steam_web_api_call(endpoint="get_trade_hold_durations", consumer="trade_link"):
        pass
    with (
        pytest.raises(RuntimeError),
        steam_web_api_call(endpoint="get_trade_hold_durations", consumer="trade_link"),
    ):
        raise RuntimeError("boom")
    assert (
        _value(endpoint="get_trade_hold_durations", consumer="trade_link", outcome="ok")
        == ok_before + 1
    )
    assert (
        _value(endpoint="get_trade_hold_durations", consumer="trade_link", outcome="error")
        == err_before + 1
    )


def test_a_broken_registry_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        def labels(self, **_: Any) -> Any:
            raise ValueError("label mismatch")

    monkeypatch.setattr(metrics, "STEAM_WEB_API_CALLS", _Broken())
    record_steam_web_api_call(endpoint="get_player_summaries", consumer="auth_signin", outcome="ok")


def test_metric_names_carry_the_csmarket_prefix() -> None:
    assert STEAM_WEB_API_CALLS._name == "csmarket_steam_web_api_calls"  # type: ignore[attr-defined]
