"""Pure helpers of ``skins.repricing`` and ``skins.settings``."""

from __future__ import annotations

from decimal import Decimal

from csmarket.core.config import Settings
from csmarket.modules.skins.repricing import discount_of
from csmarket.modules.skins.settings import enabled_categories


def test_discount_is_whole_percent_below_steam() -> None:
    assert discount_of(Decimal("31.34"), 43794) == 28  # 28.4 % truncated
    assert discount_of(Decimal("50.00"), 43794) == -14  # dearer than Steam, truncated toward zero
    assert discount_of(Decimal("1.00"), None) is None
    assert discount_of(Decimal("1.00"), 0) is None


def test_enabled_categories_parses_dedupes_and_drops_unknown() -> None:
    s = Settings(skins_categories=" Rifles,knives,,rifles,nonsense,cases ")
    assert enabled_categories(s) == ["rifles", "knives", "cases"]
