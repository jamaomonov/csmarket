"""Render a letter from its kind, the reader's locale and the outbox payload (M4b R5).

Task 3 ships the ``verify`` letter only; the order letters arrive with their copy in
ru / uz / en (Task 4), and until then rendering one raises ``NotImplementedError``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from typing import Literal

Locale = Literal["ru", "uz", "en"]


@dataclass(frozen=True, slots=True)
class Links:
    """Absolute storefront links a letter may point to, in the reader's locale."""

    order_url: str
    balance_url: str
    confirm_url: str


@dataclass(frozen=True, slots=True)
class EmailContent:
    """A rendered letter."""

    subject: str
    html: str
    text: str


_VERIFY = {
    "ru": ("Подтвердите почту", "Нажмите на ссылку, чтобы получать письма о заказах."),
    "uz": (
        "Pochtangizni tasdiqlang",
        "Buyurtmalar haqida xat olish uchun havolani bosing.",
    ),
    "en": ("Confirm your email", "Follow the link to get emails about your orders."),
}


def render(
    kind: str,
    *,
    locale: Locale,
    number: str | None,  # noqa: ARG001 -- the order letters use it (Task 4)
    payload: Mapping[str, str],  # noqa: ARG001 -- as above
    links: Links,
) -> EmailContent:
    """Render one letter.

    Raises:
        NotImplementedError: An order letter (until Task 4 adds them).
    """
    if kind != "verify":
        raise NotImplementedError(kind)
    subject, body = _VERIFY[locale]
    url = links.confirm_url
    html = f'<p>{escape(body)}</p><p><a href="{escape(url)}">{escape(url)}</a></p>'
    return EmailContent(subject=subject, html=html, text=f"{body}\n\n{url}\n")
