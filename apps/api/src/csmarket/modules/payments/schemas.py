"""Wire shapes for the customer's top-ups and the provider list."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from csmarket.core.money import wire_uzs
from csmarket.modules.payments.topups import TopupView

Locale = Literal["ru", "uz", "en"]


class ProviderOut(BaseModel):
    """A kassa the storefront may offer."""

    slug: str
    #: The percent the buyer pays on top through this kassa, e.g. ``"1.5"``; ``"0"`` for none.
    fee_pct: str
    #: ``on`` or ``maintenance`` (show the tile greyed, «Технические работы»); an ``off``
    #: kassa is not listed.
    status: Literal["on", "maintenance"] = "on"
    #: Balance top-ups only (P2P): never offered at checkout.
    topup_only: bool = False


class ProvidersOut(BaseModel):
    """The kassas available now, in the order the storefront shows them."""

    providers: list[ProviderOut]


class TopupIn(BaseModel):
    """Open a balance top-up."""

    model_config = ConfigDict(extra="forbid")

    #: Whole soʻm; a JSON integer only (``"1000"``, ``1000.5`` and ``true`` are refused).
    amount_uzs: Annotated[int, Field(strict=True)]
    provider: Annotated[str, Field(min_length=1, max_length=16)]
    #: The language of the kassa's page and of the page the customer returns to.
    locale: Locale


class P2PTransferOut(BaseModel):
    """A P2P top-up's transfer: the full card, its holder, the exact amount and the deadline."""

    card_number: str
    holder: str
    #: Whole soʻm as digits: transfer exactly this.
    amount_uzs: str
    expires_at: datetime
    status: Literal["pending", "paid", "expired", "cancelled"]


class TopupOut(BaseModel):
    """A top-up as its owner sees it."""

    number: str
    #: Whole soʻm as digits: what reaches the balance.
    amount_uzs: str
    #: The kassa fee on top, whole soʻm; ``"0"`` for none.
    fee_uzs: str
    #: What the kassa charges: ``amount_uzs + fee_uzs``.
    charge_uzs: str
    #: The kassa the top-up was opened in.
    provider: str | None
    status: Literal["pending", "succeeded", "expired", "reversed"]
    expires_at: datetime
    #: Where to pay; ``null`` once the top-up cannot be paid.
    intent_url: str | None
    #: ``pending`` while a kassa holds an attempt: it may still settle after ``expires_at``,
    #: so a ``pending`` top-up without ``intent_url`` is "being checked", not "expired".
    awaiting_kassa: bool
    #: A P2P top-up awaiting its transfer: where and how much (``null`` otherwise).
    p2p: P2PTransferOut | None = None

    @classmethod
    def of(cls, view: TopupView) -> TopupOut:
        """Build from a :class:`TopupView`."""
        t = view.topup
        return cls(
            number=t.number,
            amount_uzs=wire_uzs(t.amount_uzs),
            fee_uzs=wire_uzs(view.fee_uzs),
            charge_uzs=wire_uzs(t.amount_uzs + view.fee_uzs),
            provider=view.provider,
            status=t.status,  # type: ignore[arg-type]  # DB check constraint guarantees the set
            expires_at=t.expires_at,
            intent_url=view.intent_url,
            awaiting_kassa=view.awaiting_kassa,
            p2p=None
            if view.p2p is None
            else P2PTransferOut(
                card_number=view.p2p.card_number,
                holder=view.p2p.holder,
                amount_uzs=str(view.p2p.amount_uzs),
                expires_at=view.p2p.expires_at,
                status=view.p2p.status,  # type: ignore[arg-type]  # the reservations' check
            ),
        )


__all__ = ["Locale", "P2PTransferOut", "ProviderOut", "ProvidersOut", "TopupIn", "TopupOut"]
