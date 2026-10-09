"""API tokens (``csm_…``) never reach a log line, under a key or inside free text."""

from __future__ import annotations

from csmarket.core.logging import _redact_pii

TOKEN = "csm_AbC123-xyz_" + "q" * 30


def test_a_token_under_a_secret_key_is_redacted() -> None:
    out = _redact_pii(None, "info", {"event": "x", "token": TOKEN})
    assert TOKEN not in str(out)


def test_a_token_inside_free_text_is_replaced_and_the_rest_kept() -> None:
    out = _redact_pii(None, "info", {"event": "x", "note": f"bad key {TOKEN} from client"})
    assert out["note"] == "bad key <redacted> from client"


def test_text_without_a_token_is_untouched() -> None:
    out = _redact_pii(None, "info", {"event": "x", "note": "csmarket_orders total"})
    assert out["note"] == "csmarket_orders total"
