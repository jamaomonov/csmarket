"""``trade_sent``: the seller's trade offer is out; accept it before the deadline."""

from __future__ import annotations

from collections.abc import Mapping

from csmarket.modules.notifications.copy import COPY
from csmarket.modules.notifications.templates.base import (
    EmailContent,
    Links,
    Locale,
    compose,
    tashkent_time,
)


def build(*, locale: Locale, number: str, payload: Mapping[str, str], links: Links) -> EmailContent:
    """The trade-sent letter; ``payload["send_until"]`` (ISO, UTC) is the deadline if known."""
    words = COPY[locale]
    deadline = tashkent_time(payload.get("send_until", ""))
    body = (
        words["trade_sent.body"].format(time=deadline)
        if deadline
        else words["trade_sent.body_open"]
    )
    return compose(
        locale=locale,
        subject=words["trade_sent.subject"].format(number=number),
        body=body,
        href=links.order_url,
        label=words["button.order"],
        links=links,
    )
