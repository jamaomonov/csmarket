"""Domain counters never fail a request and carry only closed label sets."""

from __future__ import annotations

from typing import Any

import pytest
from csmarket.core import metrics
from csmarket.core.metrics import (
    KASSA_REJECTIONS,
    STEAM_WEB_API_CALLS,
    record_kassa_rejection,
    record_steam_web_api_call,
    steam_web_api_call,
)


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


def _rejections(provider: str, reason: str) -> float:
    return KASSA_REJECTIONS.labels(provider=provider, reason=reason)._value.get()  # type: ignore[no-any-return]


def test_kassa_rejection_increments_the_labelled_series() -> None:
    before = _rejections("click", "signature")
    record_kassa_rejection(provider="click", reason="signature")
    assert _rejections("click", "signature") == before + 1


def test_kassa_rejection_unknown_labels_collapse_to_other() -> None:
    # A caller passing an identifier where a verdict goes must not mint a new series.
    before = _rejections("other", "other")
    record_kassa_rejection(provider="76561198000000000", reason="198.51.100.7")  # type: ignore[arg-type]
    assert _rejections("other", "other") == before + 1
    known = {
        tuple(sample.labels.values())
        for family in KASSA_REJECTIONS.collect()
        for sample in family.samples
    }
    assert ("76561198000000000", "198.51.100.7") not in known


def test_kassa_rejection_keeps_a_known_provider_with_an_unknown_reason() -> None:
    before = _rejections("payme", "other")
    record_kassa_rejection(provider="payme", reason="whatever")  # type: ignore[arg-type]
    assert _rejections("payme", "other") == before + 1


def test_a_broken_kassa_registry_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        def labels(self, **_: Any) -> Any:
            raise ValueError("label mismatch")

    monkeypatch.setattr(metrics, "KASSA_REJECTIONS", _Broken())
    record_kassa_rejection(provider="uzum", reason="auth")


def test_kassa_rejection_metric_name_carries_the_csmarket_prefix() -> None:
    assert KASSA_REJECTIONS._name == "csmarket_kassa_rejections"  # type: ignore[attr-defined]


def _waxpeer(endpoint: str, outcome: str) -> float:
    return metrics.WAXPEER_CALLS.labels(endpoint=endpoint, outcome=outcome)._value.get()  # type: ignore[no-any-return]


def test_waxpeer_calls_are_counted_and_unknown_labels_collapse() -> None:
    ok_before = _waxpeer("buy", "forbidden")
    other_before = _waxpeer("other", "other")
    metrics.record_waxpeer_call("buy", "forbidden")
    metrics.record_waxpeer_call("sell", "maybe")  # type: ignore[arg-type]
    assert _waxpeer("buy", "forbidden") == ok_before + 1
    assert _waxpeer("other", "other") == other_before + 1


def test_waxpeer_recording_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        def labels(self, **_: Any) -> Any:
            raise ValueError("label mismatch")

    monkeypatch.setattr(metrics, "WAXPEER_CALLS", _Broken())
    metrics.record_waxpeer_call("lookup", "ok")
