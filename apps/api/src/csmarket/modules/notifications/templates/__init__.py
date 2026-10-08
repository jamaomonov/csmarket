"""Render a letter from its kind, the reader's locale and the outbox payload (M4b T4).

Copy lives in :mod:`csmarket.modules.notifications.copy` (ru / uz / en); the shell in
:mod:`.layout`. Letters never carry a trade link, a Steam ID or the buyer's balance.
"""

from __future__ import annotations

from collections.abc import Mapping

from csmarket.modules.notifications.templates import receipt, refunded, sale, trade_sent, verify
from csmarket.modules.notifications.templates.base import EmailContent, Links, Locale

_ORDER_LETTERS = {
    "receipt": receipt.build,
    "trade_sent": trade_sent.build,
    "refunded": refunded.build,
    "sale_hold": sale.hold,
    "sale_paid": sale.paid,
    "sale_canceled": sale.canceled,
}


def render(
    kind: str,
    *,
    locale: Locale,
    number: str | None,
    payload: Mapping[str, str],
    links: Links,
) -> EmailContent:
    """Render one letter.

    Args:
        kind: ``receipt``, ``trade_sent``, ``refunded``, a sale letter or ``verify``.
        locale: The reader's locale.
        number: The order's or sale's number; ``None`` for ``verify``.
        payload: The outbox row's strings.
        links: Absolute storefront links in ``locale``.

    Raises:
        ValueError: An unknown kind, or an order letter without a number.
    """
    if kind == "verify":
        return verify.build(locale=locale, links=links)
    build = _ORDER_LETTERS.get(kind)
    if build is None:
        raise ValueError(f"unknown letter kind {kind!r}")
    if not number:
        raise ValueError(f"a {kind} letter needs an order number")
    return build(locale=locale, number=number, payload=payload, links=links)


__all__ = ["EmailContent", "Links", "Locale", "render"]
