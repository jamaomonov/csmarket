"""Header validation for the generic replay store (the DB half is an integration test)."""

from __future__ import annotations

import pytest
from csmarket.core.errors import ValidationError
from csmarket.core.idempotency import (
    IDEMPOTENCY_HEADER,
    MIN_IDEMPOTENCY_KEY_LENGTH,
    normalize_idempotency_key,
)


def test_absent_header_means_no_replay() -> None:
    assert normalize_idempotency_key(None) is None


def test_a_long_enough_key_passes_through() -> None:
    key = "a" * MIN_IDEMPOTENCY_KEY_LENGTH
    assert normalize_idempotency_key(key) == key


def test_a_short_key_is_rejected_not_silently_accepted() -> None:
    with pytest.raises(ValidationError) as exc:
        normalize_idempotency_key("short")
    assert exc.value.extra == {"header": IDEMPOTENCY_HEADER}
