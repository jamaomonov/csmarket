"""``core.json_stream.ItemsScanner`` with a caller's own envelope (LIS-SKINS' export)."""

from __future__ import annotations

import json
import re

import pytest
from csmarket.core.json_stream import ItemsScanner

STATUS = re.compile(r'"status"\s*:\s*"success"')
LAST = re.compile(r'"last_update"\s*:\s*([0-9]+)')
BODY = json.dumps(
    {
        "status": "success",
        "last_update": 1759831200,
        "items": [{"id": 1, "name": "a ] {"}, {"id": 2, "stickers": [{"name": "x"}]}],
    }
)


@pytest.mark.parametrize("chunk", [1, 5, 64, 100_000])
def test_a_status_envelope_reads_with_its_own_patterns(chunk: int) -> None:
    scanner = ItemsScanner(success=STATUS, cursor=LAST)
    found: list[object] = []
    for start in range(0, len(BODY), chunk):
        found += scanner.feed(BODY[start : start + chunk])
    assert [o["id"] for o in found if isinstance(o, dict)] == [1, 2]
    assert scanner.finish() == "1759831200"


def test_the_default_patterns_refuse_a_status_envelope() -> None:
    scanner = ItemsScanner()
    scanner.feed(BODY)
    with pytest.raises(ValueError, match="not a success"):
        scanner.finish()


def test_a_failed_status_is_not_a_success() -> None:
    scanner = ItemsScanner(success=STATUS, cursor=LAST)
    scanner.feed(BODY.replace('"success"', '"error"'))
    with pytest.raises(ValueError, match="not a success"):
        scanner.finish()


def test_a_body_cut_inside_the_array_is_truncated() -> None:
    scanner = ItemsScanner(success=STATUS, cursor=LAST)
    scanner.feed(BODY[: BODY.index('{"id": 2')])
    with pytest.raises(ValueError, match="truncated"):
        scanner.finish()


def test_a_broken_item_never_holds_the_rest_of_the_body() -> None:
    """A malformed element is not "an item cut by the chunk": the buffer stops growing."""
    scanner = ItemsScanner()
    scanner.feed('{"success": true, "data": {"items": [{"id": 1}, {"id": oops}, ')
    filler = '{"id": 2, "pad": "' + "x" * 4096 + '"}, '
    for _ in range(250):  # ~1 MB after the broken element: still within the cap
        scanner.feed(filler)
    with pytest.raises(ValueError, match="item"):
        scanner.feed(filler * 10)
