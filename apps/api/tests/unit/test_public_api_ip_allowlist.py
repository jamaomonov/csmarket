"""The key's IP allow-list normaliser."""

from __future__ import annotations

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.public_api.ip_allowlist import MAX_ENTRIES, normalise


def test_normalises_and_dedupes() -> None:
    assert normalise([" 203.0.113.7 ", "203.0.113.7/32", "10.1.2.3/8", "2001:DB8::1"]) == [
        "203.0.113.7/32",
        "10.0.0.0/8",
        "2001:db8::1/128",
    ]


def test_empty_is_any() -> None:
    assert normalise([]) == []


def test_longest_canonical_form_fits_the_column() -> None:
    (net,) = normalise(["2001:db8:1111:2222:3333:4444:5555:6666"])
    assert len(net) <= 43


@pytest.mark.parametrize("bad", ["", "999.1.1.1", "example.com", "10.0.0.0/33", "fe80::1%eth0"])
def test_bad_entry_names_its_index(bad: str) -> None:
    with pytest.raises(ValidationError) as err:
        normalise(["203.0.113.7", bad])
    assert err.value.extra == {"code": "ip_allowlist_invalid", "index": 1}


def test_cap() -> None:
    with pytest.raises(ValidationError) as err:
        normalise([f"10.0.0.{i}" for i in range(MAX_ENTRIES + 1)])
    assert err.value.extra == {"code": "ip_allowlist_invalid", "index": MAX_ENTRIES}
