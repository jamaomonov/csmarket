"""Slug assignment: a free slug stays, a taken one gets a stable hex suffix."""

from __future__ import annotations

from csmarket.modules.skins.slugs import resolve, suffixed

Key = tuple[str, str]


def test_free_slug_is_kept() -> None:
    key = ("AK-47 | Redline (Field-Tested)", "")
    out = resolve([(key, "ak-47-redline-field-tested")], {})
    assert out == {key: "ak-47-redline-field-tested"}


def test_existing_row_keeps_its_slug_forever() -> None:
    key = ("AK-47 | Redline (Field-Tested)", "")
    assert resolve([(key, "new-plain-slug")], {key: "old-slug"}) == {key: "old-slug"}


def test_colliding_slug_gets_a_stable_hex_suffix() -> None:
    key = ("★ Karambit | Doppler (Factory New)", "Phase 2")
    other = ("Karambit | Doppler (Factory New)", "Phase 2")
    plain = "karambit-doppler-factory-new-phase-2"
    taken: dict[Key, str] = {other: plain}
    out = resolve([(key, plain)], taken)
    assert out[key] != plain
    assert out[key] == suffixed(plain, key)
    assert out[key] == resolve([(key, plain)], taken)[key]


def test_two_new_rows_wanting_one_slug_both_get_distinct_slugs() -> None:
    a, b = ("A", ""), ("B", "")
    out = resolve([(a, "same"), (b, "same")], {})
    assert len(set(out.values())) == 2
    assert out[a] == "same"
    assert out[b] == suffixed("same", b)
