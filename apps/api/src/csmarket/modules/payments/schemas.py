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


class TopupOut(BaseModel):
    """A top-up as its owner sees it."""

    number: str
    #: Whole soʻm as digits.
    amount_uzs: str
    #: The kassa the top-up was opened in.
    provider: str | None
    status: Literal["pending", "succeeded", "expired", "reversed"]
    expires_at: datetime
    #: Where to pay; ``null`` once the top-up cannot be paid.
    intent_url: str | None

    @classmethod
    def of(cls, view: TopupView) -> TopupOut:
        """Build from a :class:`TopupView`."""
        t = view.topup
        return cls(
            number=t.number,
            amount_uzs=wire_uzs(t.amount_uzs),
            provider=view.provider,
            status=t.status,  # type: ignore[arg-type]  # DB check constraint guarantees the set
            expires_at=t.expires_at,
            intent_url=view.intent_url,
        )


__all__ = ["Locale", "ProviderOut", "ProvidersOut", "TopupIn", "TopupOut"]
