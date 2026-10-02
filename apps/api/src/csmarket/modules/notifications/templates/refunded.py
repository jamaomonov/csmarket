"""``refunded``: the trade did not happen and the money is back on the balance."""

from __future__ import annotations

from collections.abc import Mapping

from csmarket.modules.notifications.copy import COPY
from csmarket.modules.notifications.templates.base import (
    EmailContent,
    Links,
    Locale,
    amount,
    compose,
)


def build(*, locale: Locale, number: str, payload: Mapping[str, str], links: Links) -> EmailContent:
    """The refund letter; ``payload["amount_uzs"]`` is the whole-soʻm amount returned."""
    words = COPY[locale]
    return compose(
        locale=locale,
        subject=words["refunded.subject"].format(number=number),
        body=words["refunded.body"].format(amount=amount(payload.get("amount_uzs", "0"), locale)),
        href=links.balance_url,
        label=words["button.balance"],
        links=links,
    )
