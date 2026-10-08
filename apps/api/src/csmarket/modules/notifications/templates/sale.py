"""Sale letters (spec 2026-10-08 §8): the trade accepted, the money sent, the sale off.

The reader sold skins and waits for money: no names of who buys them, no "hold", no
"deposit". A card is named by its last four digits only.
"""

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


def hold(*, locale: Locale, number: str, payload: Mapping[str, str], links: Links) -> EmailContent:
    """The trade is accepted; the money comes in 7 days."""
    words = COPY[locale]
    return compose(
        locale=locale,
        subject=words["sale_hold.subject"].format(number=number),
        body=words["sale_hold.body"].format(amount=amount(payload.get("amount_uzs", "0"), locale)),
        href=links.sale_url,
        label=words["button.sale"],
        links=links,
    )


def paid(*, locale: Locale, number: str, payload: Mapping[str, str], links: Links) -> EmailContent:
    """The money is on the balance (``to`` = ``balance``) or sent to a card (``card``)."""
    words = COPY[locale]
    money = amount(payload.get("amount_uzs", "0"), locale)
    to_card = payload.get("to") == "card"
    last4 = payload.get("last4", "")
    if payload.get("rejected") == "true":
        key = "sale_paid.body_rejected_card" if last4 else "sale_paid.body_rejected"
        body = words[key].format(amount=money, last4=last4, reason=payload.get("reason", ""))
    elif to_card:
        body = words["sale_paid.body_card"].format(amount=money, last4=last4)
    else:
        body = words["sale_paid.body_balance"].format(amount=money)
    return compose(
        locale=locale,
        subject=words["sale_paid.subject"].format(number=number),
        body=body,
        href=links.sale_url if to_card else links.balance_url,
        label=words["button.sale"] if to_card else words["button.balance"],
        links=links,
    )


def canceled(
    *,
    locale: Locale,
    number: str,
    payload: Mapping[str, str],  # noqa: ARG001 -- the builders share one signature
    links: Links,
) -> EmailContent:
    """The sale did not go through; nothing is paid."""
    words = COPY[locale]
    return compose(
        locale=locale,
        subject=words["sale_canceled.subject"].format(number=number),
        body=words["sale_canceled.body"],
        href=links.sale_url,
        label=words["button.sale"],
        links=links,
    )
