"""The sale-settings document an admin edits (spec 2026-10-08 §3, §4): ``sale_settings`` row 1.

The margin is progressive by price bracket like the retail brackets (``skins.Bracket``,
reused), but here it is taken **off** Skinslink's price. Fees and the bonus are percents; the
minimum sum is Skinslink's own (1 $) or more. The default ships switched off: the owner sets
the real fees before turning selling on (the card fees below are the demo's placeholders).

The three USD ceilings (per sale, per seller per 24 h, everyone per 24 h) are optional: a
missing key or ``null`` is no limit, so a document saved before they existed reads as before.
:func:`settings_warnings` names a document that loses money; it never blocks a save.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from csmarket.modules.skins.api import Bracket

CardType = Literal["uzcard", "humo", "uzum_visa"]
PayoutTo = Literal["balance", "card"]
#: ``balance_bonus_eats_margin``: the top bracket's margin less the balance bonus less the 1 %
#: Skinslink may credit under our quote (``min_prices``) is zero or less — an expensive sale
#: to the balance loses money.
SettingsWarning = Literal["balance_bonus_eats_margin"]

#: A margin bracket keeps less than all of the price.
_MAX_PERCENT = Decimal(100)
#: How far under our quote Skinslink may credit us (``pricing.min_prices``: 99 %).
_CREDIT_GAP_PCT = Decimal(1)


#: A USD ceiling (an optional field: ``None`` is no limit).
UsdLimit = Annotated[Decimal, Field(gt=0, le=10_000_000, max_digits=12, decimal_places=2)]


class CardFees(BaseModel):
    """The fee kept on a payout to each card type, percent."""

    model_config = ConfigDict(frozen=True)

    uzcard: Decimal = Field(ge=0, le=50, max_digits=5, decimal_places=2)
    humo: Decimal = Field(ge=0, le=50, max_digits=5, decimal_places=2)
    uzum_visa: Decimal = Field(ge=0, le=50, max_digits=5, decimal_places=2)

    def of(self, card_type: CardType) -> Decimal:
        """The fee of ``card_type``."""
        return {"uzcard": self.uzcard, "humo": self.humo, "uzum_visa": self.uzum_visa}[card_type]


class SaleSettings(BaseModel):
    """The whole document, as stored in ``sale_settings.settings``."""

    model_config = ConfigDict(frozen=True)

    #: «Выкуп включён»; ``CSMARKET_SALES_ENABLED`` must be on too.
    enabled: bool = False
    #: Our margin, taken off Skinslink's price: each bracket's percent on its slice.
    margin: list[Bracket] = Field(min_length=1)
    #: Percent taken off the CBU rate (the buy side's 1 % uplift is never applied here).
    rate_cut_pct: Decimal = Field(default=Decimal(0), ge=0, le=20, max_digits=5, decimal_places=2)
    #: Percent added to a payout to the balance.
    balance_bonus_pct: Decimal = Field(ge=0, le=20, max_digits=5, decimal_places=2)
    card_fee_pct: CardFees
    #: What the bank charges the sender on a card transfer, percent (owner 2026-10-13: 1 %);
    #: the P&L adds it to each card payout (spec 2026-10-13-sales-pnl).
    bank_fee_pct: Decimal = Field(default=Decimal(1), ge=0, le=10, max_digits=4, decimal_places=2)
    #: The smallest payout to a card, whole soʻm.
    card_min_uzs: int = Field(ge=0, le=100_000_000)
    #: The smallest sum of the chosen items' Skinslink prices, USD (Skinslink's floor is 1).
    #: Skinslink refuses a deposit of exactly 1 $ (400 ``gt``, 2026-10-08): strictly above it.
    min_sum_usd: Decimal = Field(
        default=Decimal("1.10"), gt=1, le=1000, max_digits=7, decimal_places=2
    )
    #: The most one sale may be worth (Σ Skinslink prices), USD; ``None``: no limit.
    max_sale_usd: UsdLimit | None = None
    #: The most one seller may sell in the last 24 h, USD; ``None``: no limit.
    max_user_day_usd: UsdLimit | None = None
    #: The most everyone together may sell in the last 24 h, USD; ``None``: no limit.
    max_day_usd: UsdLimit | None = None

    @model_validator(mode="after")
    def _brackets(self) -> SaleSettings:
        if self.margin[0].from_usd != 0:
            raise ValueError("margin: the first bracket must start at 0")
        for prev, cur in pairwise(self.margin):
            if cur.from_usd <= prev.from_usd:
                raise ValueError("margin: brackets must ascend strictly")
        if any(not 0 <= b.percent < _MAX_PERCENT for b in self.margin):
            raise ValueError("margin: every percent is at least 0 and under 100")
        return self


def settings_warnings(doc: SaleSettings) -> list[SettingsWarning]:
    """What in ``doc`` loses money (shown beside the settings; a save is never refused)."""
    top = doc.margin[-1].percent
    if top - doc.balance_bonus_pct - _CREDIT_GAP_PCT <= 0:
        return ["balance_bonus_eats_margin"]
    return []


DEFAULT_SALE_SETTINGS = SaleSettings(
    enabled=False,
    # The spec's example brackets (2026-10-08).
    margin=[
        Bracket(from_usd=Decimal(0), percent=Decimal(10)),
        Bracket(from_usd=Decimal(1), percent=Decimal(5)),
        Bracket(from_usd=Decimal(10), percent=Decimal(3)),
        Bracket(from_usd=Decimal(100), percent=Decimal(2)),
    ],
    rate_cut_pct=Decimal(0),
    balance_bonus_pct=Decimal(2),
    card_fee_pct=CardFees(uzcard=Decimal(5), humo=Decimal(5), uzum_visa=Decimal(5)),
    card_min_uzs=30_000,
    min_sum_usd=Decimal("1.10"),
)

__all__ = [
    "DEFAULT_SALE_SETTINGS",
    "CardFees",
    "CardType",
    "PayoutTo",
    "SaleSettings",
    "SettingsWarning",
    "settings_warnings",
]
