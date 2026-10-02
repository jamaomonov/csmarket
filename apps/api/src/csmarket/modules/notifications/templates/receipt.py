"""``receipt``: the order is paid and the skin is being bought."""

from __future__ import annotations

from collections.abc import Mapping

from csmarket.modules.notifications.copy import COPY
from csmarket.modules.notifications.templates.base import EmailContent, Links, Locale, compose


def build(*, locale: Locale, number: str, payload: Mapping[str, str], links: Links) -> EmailContent:
    """The receipt letter; ``payload["skin"]`` names the item."""
    words = COPY[locale]
    return compose(
        locale=locale,
        subject=words["receipt.subject"].format(number=number),
        body=words["receipt.body"].format(skin=payload.get("skin", "")),
        href=links.order_url,
        label=words["button.order"],
        links=links,
    )
