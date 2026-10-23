"""The reviews vocabulary (spec 2026-10-23-reviews-design)."""

from datetime import timedelta

from csmarket.modules.reviews.models import (
    GOOD_FROM,
    REVIEW_KINDS,
    REVIEW_LOCALES,
    REVIEW_WINDOW,
    SNOOZE,
    TEXT_MAX,
    Review,
    ReviewPrompt,
    ReviewSettingsRow,
)


def test_vocabulary() -> None:
    assert REVIEW_KINDS == ("market", "sale")
    assert REVIEW_LOCALES == ("ru", "uz", "en")
    assert (GOOD_FROM, TEXT_MAX) == (4, 1000)
    assert timedelta(days=14) == REVIEW_WINDOW
    assert timedelta(days=3) == SNOOZE


def test_tables() -> None:
    assert Review.__tablename__ == "reviews"
    assert ReviewPrompt.__tablename__ == "review_prompts"
    assert ReviewSettingsRow.__tablename__ == "review_settings"
