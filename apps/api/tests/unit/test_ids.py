"""App-side UUIDv7 ids: sortable, 36 chars, unique."""

from __future__ import annotations

import uuid

from csmarket.core.ids import new_id


def test_new_id_is_a_uuid_string() -> None:
    value = new_id()
    assert len(value) == 36
    assert uuid.UUID(value).version == 7


def test_ids_are_monotonic_enough_to_sort_by_time() -> None:
    first, second = new_id(), new_id()
    assert first != second
    assert first < second
