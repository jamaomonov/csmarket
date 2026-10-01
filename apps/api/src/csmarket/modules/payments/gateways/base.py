"""The payment-gateway contract (ruling R10).

A gateway only turns a payable into the URL the customer is sent to; it writes nothing.
``hooks.ensure_attempt`` owns the attempt row, and each kassa's callbacks live in its own
module (``click``, ``payme``, ``uzum``). Every gateway returns the customer to our own page
of the payable — a top-up's or an order's (:func:`return_url`) — there is no
client-supplied return URL to validate.
"""

from __future__ import annotations

from typing import Protocol

from csmarket.core.config import get_settings
from csmarket.core.numbers import TOPUP_PREFIX
from csmarket.modules.payments.payable import Payable

#: Storefront path prefix per locale; ``ru`` is the default locale and has none.
_LOCALE_PREFIX = {"ru": "", "uz": "/uz", "en": "/en"}


class PaymentGateway(Protocol):
    """What every kassa adapter (and the dev ``mock``) provides."""

    #: The slug stored in ``payments.provider``: ``click``, ``payme``, ``uzum``, ``mock``.
    provider: str

    @property
    def available(self) -> bool:
        """Whether this gateway can take payments here (credentials set, not prod for mock)."""
        ...

    def intent_url(self, *, payable: Payable, locale: str) -> str:
        """Where to send the customer to pay ``payable``, in the kassa's ``locale`` page."""
        ...


def return_url(number: str, locale: str) -> str:
    """The storefront page of payable ``number``.

    A top-up (``T…``): ``{web_base_url}[/uz|/en]/account/balance/topups/{number}``; any other
    number is an order: ``{web_base_url}[/uz|/en]/orders/{number}``.

    Raises:
        ValueError: ``locale`` is not ``ru``, ``uz`` or ``en``.
    """
    try:
        prefix = _LOCALE_PREFIX[locale]
    except KeyError:
        raise ValueError(f"unsupported locale {locale!r}") from None
    base = get_settings().web_base_url.rstrip("/")
    if number.startswith(TOPUP_PREFIX):
        return f"{base}{prefix}/account/balance/topups/{number}"
    return f"{base}{prefix}/orders/{number}"


__all__ = ["PaymentGateway", "return_url"]
