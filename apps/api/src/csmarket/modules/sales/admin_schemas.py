"""Admin wire shapes of ``sales`` (spec 2026-10-08 §7). Money as strings; a card by its last
four — the full number only in :class:`RevealOut`, which is never stored as a replay."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from csmarket.modules.sales.rules import CardType, PayoutTo, SaleSettings, SettingsWarning
from csmarket.modules.sales.schemas import PayoutStatusOut, SaleStatusOut

#: Why a sale waits for an admin (``sales.models.ATTENTION_REASONS``).
AttentionReasonOut = Literal["rolled_back", "late_deposit", "credit_blocked"]
#: The sales list's attention filter: ``open`` (unresolved), ``resolved``, ``any`` (either).
AttentionFilter = Literal["open", "resolved", "any"]
#: A payout row's risk flags (``admin_risk``).
PayoutFlag = Literal[
    "banned",
    "wallet_frozen",
    "sell_blocked",
    "new_account",
    "shared_card",
    "rolled_back",
    "seller_reverted",
]
#: The queue's tab: one status, or ``all`` (a search across every status, newest first).
PayoutTab = Literal["to_pay", "waiting_hold", "paid", "rejected", "canceled", "all"]


class AdminUserOut(BaseModel):
    """A user as the admin lists name them."""

    id: str
    display_name: str | None
    #: The Steam avatar; ``null`` when Steam gave none.
    avatar_url: str | None = None


class PayoutRowOut(BaseModel):
    """A payout request in the queue."""

    id: str
    sale_number: str
    user: AdminUserOut
    card_type: CardType
    #: ``•••• 9015``.
    card_masked: str
    amount_uzs: str
    fee_uzs: str
    status: PayoutStatusOut
    #: Since when it is payable.
    to_pay_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    #: «Беру в работу»: who pays it now and until when; ``null`` when free or expired.
    claimed_by: AdminUserOut | None = None
    claimed_until: datetime | None = None
    #: What to look at before paying (``banned``, ``wallet_frozen``, …).
    flags: list[PayoutFlag] = Field(default_factory=list)


class PayoutCountsOut(BaseModel):
    """Requests per status (the tabs)."""

    waiting_hold: int = 0
    to_pay: int = 0
    paid: int = 0
    rejected: int = 0
    canceled: int = 0


class PayoutTotalsOut(BaseModel):
    """The queue's strip: payable now, and decided since midnight in Tashkent."""

    to_pay_count: int
    to_pay_uzs: str
    paid_today_count: int
    paid_today_uzs: str
    rejected_today_count: int


class PayoutsPageOut(BaseModel):
    """One page of a status tab, every tab's count, the day's totals and the next cursor."""

    items: list[PayoutRowOut]
    counts: PayoutCountsOut
    totals: PayoutTotalsOut
    next_cursor: str | None


class PayoutRiskOut(BaseModel):
    """«Риски»: who the seller is and how much went to them and to this card."""

    #: The seller's Steam profile (admin only).
    steam_url: str | None
    account_created_at: datetime | None
    banned: bool
    ban_reason: str | None
    wallet_frozen: bool
    sell_blocked: bool
    sell_block_reason: str | None
    #: Sales that paid or will pay the seller, and their soʻm.
    sold_count: int
    sold_uzs: str
    #: Card payouts already paid to the seller.
    paid_count: int
    paid_uzs: str
    #: Paid to this card number on any account.
    card_paid_uzs: str
    #: The seller's sales of the last 24 h (not closed or reverted), USD at Skinslink's prices.
    day_count: int
    day_usd: str
    #: The card has a fingerprint (``false``: saved before 0033 and not backfilled yet).
    card_known: bool
    #: Other accounts that saved the same card.
    shared_card_users: list[AdminUserOut]


class AdminSaleItemOut(BaseModel):
    """One skin of a sale with both prices."""

    asset_id: str
    name: str
    image_url: str | None = None
    #: Skinslink's price.
    price_usd: str
    #: Ours.
    price_uzs: str


class AdminSaleSkinOut(BaseModel):
    """A skin of a sale in a list: its name and picture."""

    name: str
    image_url: str | None


class AdminSaleRowOut(BaseModel):
    """A sale as the admin list shows it."""

    number: str
    status: SaleStatusOut
    user: AdminUserOut
    payout_to: PayoutTo
    quoted_usd: str
    payout_uzs: str
    margin_usd: str
    attention_reason: AttentionReasonOut | None
    #: The attention is set and no admin marked it checked yet.
    attention_open: bool
    created_at: datetime
    #: The dearest skin of the sale, for the list (``None`` on a row that does not carry it).
    first_item: AdminSaleSkinOut | None = None
    #: How many skins the sale has (``0`` on a row that does not carry it).
    items_count: int = 0


class AdminUserSaleOut(AdminSaleRowOut):
    """A sale on the user page: the row and the skins it sold."""

    items: list[AdminSaleSkinOut]


class AdminUserSalesOut(BaseModel):
    """The user page's «Продажи»: the totals and the latest sales, newest first."""

    #: Sales whose skins reached us (``hold`` onwards, never ``reverted``).
    sold_count: int
    #: Their payouts, whole soʻm.
    sold_uzs: str
    items: list[AdminUserSaleOut]


class AdminSalesPageOut(BaseModel):
    """One page of sales, the next cursor and how many sales have an open attention."""

    items: list[AdminSaleRowOut]
    next_cursor: str | None
    #: Every sale with an open attention, whatever the filters (the tab's badge).
    attention_open: int


class AdminSaleOut(BaseModel):
    """A sale's page: Skinslink's side, our payout, our margin."""

    number: str
    status: SaleStatusOut
    user: AdminUserOut
    payout_to: PayoutTo
    card_type: CardType | None
    card_masked: str | None
    quoted_usd: str
    amount_usd: str | None
    items_uzs: str
    bonus_uzs: str
    fee_uzs: str
    payout_uzs: str
    rate: str
    margin_usd: str
    trade_id: int | None
    trade_offer_id: str | None
    bot_name: str | None
    offer_expiry_at: datetime | None
    hold_end_at: datetime | None
    fail_reason: str | None
    attention_reason: AttentionReasonOut | None
    attention_open: bool
    #: «Проверено»: when, by whom, the admin's note.
    resolved_at: datetime | None
    resolved_by: AdminUserOut | None
    resolved_note: str | None
    credited_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[AdminSaleItemOut]
    payout: PayoutRowOut | None


class PayoutProofOut(BaseModel):
    """A receipt attached to a paid payout (ADR-0024); the bytes come from its own route."""

    id: str
    #: As uploaded, cleaned; PII (may name the seller), admins only.
    name: str
    #: ``image/jpeg``, ``image/png``, ``image/webp`` or ``application/pdf``.
    content_type: str
    size: int
    uploaded_by: AdminUserOut | None
    created_at: datetime
    #: «Удалить» is possible until then (10 minutes after the upload); ``null`` after.
    delete_until: datetime | None


class PayoutDetailOut(BaseModel):
    """A request's page: the request, its sale, the seller's history, what may be done."""

    request: PayoutRowOut
    note: str | None
    reject_reason: str | None
    decided_by: AdminUserOut | None
    sale: AdminSaleOut
    history_sales: list[AdminSaleRowOut]
    history_payouts: list[PayoutRowOut]
    #: «Выплачено» and «Отклонить» are possible (the request is ``to_pay``).
    can_decide: bool
    #: «Отменить (откат)» is possible: ``to_pay`` and the sale reverted after it became
    #: payable (``attention_reason = rolled_back``).
    can_cancel: bool
    #: «Вернуть в очередь» is possible until then (a decision of the last minutes).
    undo_until: datetime | None = None
    #: «Выплачено» needs ``override_reason``: the account is banned or its wallet frozen.
    paid_needs_override: bool = False
    risk: PayoutRiskOut | None = None
    #: «Подтверждение оплаты», oldest first; at most ``admin_proofs.MAX_PROOFS``.
    proofs: list[PayoutProofOut] = []


class RevealIn(BaseModel):
    """Why the admin asks for the number: to look at it or to copy it."""

    purpose: Literal["show", "copy"]


class RevealOut(BaseModel):
    """The full card number, once, in this body only."""

    #: The full card number. PII: shown to the admin, never stored or logged.
    number: str


class PaidIn(BaseModel):
    """«Выплачено» with an optional note; ``override_reason`` pays a banned account or a
    frozen wallet anyway (audited)."""

    note: str | None = Field(default=None, max_length=500)
    override_reason: str | None = Field(default=None, max_length=500)


class ClaimIn(BaseModel):
    """«Беру в работу»; ``takeover`` takes a request another admin holds."""

    takeover: bool = False


class UndoIn(BaseModel):
    """«Вернуть в очередь» with the reason (required)."""

    reason: str = Field(min_length=1, max_length=500)


class RejectIn(BaseModel):
    """«Отклонить» with the reason (required)."""

    reason: str = Field(min_length=1, max_length=500)


class CancelIn(BaseModel):
    """«Отменить (откат)» with the reason (required)."""

    reason: str = Field(min_length=1, max_length=500)


class ResolveIn(BaseModel):
    """«Проверено» with an optional note."""

    note: str | None = Field(default=None, max_length=500)


class SellBlockIn(BaseModel):
    """Block a user from selling (a reason is required) or lift the block."""

    blocked: bool
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _reason(self) -> SellBlockIn:
        if self.blocked and not (self.reason and self.reason.strip()):
            raise ValueError("a block needs a reason")
        return self


class SellBlockOut(BaseModel):
    """Whether a user may sell; who blocked them, when and why."""

    user: AdminUserOut
    blocked: bool
    reason: str | None
    blocked_by: AdminUserOut | None
    blocked_at: datetime | None


class SellBlocksOut(BaseModel):
    """Every blocked user, newest block first."""

    items: list[SellBlockOut]


class SaleSettingsOut(BaseModel):
    """The saved document, who saved it and when, the rate now and what in it loses money."""

    settings: SaleSettings
    updated_at: datetime | None
    updated_by: AdminUserOut | None
    #: The CBU rate now (no uplift), before ``rate_cut_pct``; ``null`` without one.
    rate_uzs: str | None
    #: Advice, never a refusal: ``balance_bonus_eats_margin`` — the top margin bracket less the
    #: balance bonus less 1 % is zero or less.
    warnings: list[SettingsWarning]
