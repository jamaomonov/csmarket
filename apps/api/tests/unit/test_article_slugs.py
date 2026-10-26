"""Article slug rules (spec 2026-10-26-articles)."""

from __future__ import annotations

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.articles.slugs import RESERVED_SLUGS, validate_slug


@pytest.mark.parametrize("slug", ["top-budget-knives", "ak-47-tier-list", "cs2", "a" * 80])
def test_latin_lowercase_digits_and_dashes_pass(slug: str) -> None:
    assert validate_slug(slug) == slug


@pytest.mark.parametrize(
    "slug",
    ["ab", "a" * 81, "Top-Knives", "топ-ножей", "top_knives", "top knives", "-top", "top-", "a--b"],
)
def test_bad_slugs_are_refused(slug: str) -> None:
    with pytest.raises(ValidationError) as e:
        validate_slug(slug)
    assert e.value.extra["code"] == "slug_invalid"


@pytest.mark.parametrize("slug", sorted(RESERVED_SLUGS))
def test_section_words_are_reserved(slug: str) -> None:
    with pytest.raises(ValidationError):
        validate_slug(slug)
