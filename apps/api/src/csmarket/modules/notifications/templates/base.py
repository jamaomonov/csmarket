"""What every letter shares: its parts, its links, and how amounts and times read (M4b T4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from csmarket.modules.notifications.copy import COPY
from csmarket.modules.notifications.templates.layout import (
    button,
    fallback_link,
    page,
    paragraph,
)

Locale = Literal["ru", "uz", "en"]
#: Tashkent has no daylight saving: UTC+5 all year.
TASHKENT = timezone(timedelta(hours=5))


@dataclass(frozen=True, slots=True)
class Links:
    """Absolute storefront links a letter may point to, in the reader's locale."""

    order_url: str
    balance_url: str
    confirm_url: str
    home_url: str = "https://csmarket.uz"


@dataclass(frozen=True, slots=True)
class EmailContent:
    """A rendered letter."""

    subject: str
    html: str
    text: str


def compose(
    *,
    locale: Locale,
    subject: str,
    body: str,
    href: str,
    label: str,
    links: Links,
) -> EmailContent:
    """The HTML and plain-text letter: heading = subject, one paragraph, one button."""
    html = page(
        locale=locale,
        heading=subject,
        body_html=paragraph(body)
        + button(href=href, label=label)
        + fallback_link(href=href, locale=locale),
        site_url=links.home_url,
    )
    words = COPY[locale]
    text = f"{subject}\n\n{body}\n\n{label}: {href}\n\n—\n{words['footer']}\n"
    return EmailContent(subject=subject, html=html, text=text)


def amount(value: str, locale: Locale) -> str:
    """Whole soʻm with the locale's grouping and word: ``1 250 000 сум``, ``1,250,000 UZS``."""
    try:
        whole = int(Decimal(value))
    except (InvalidOperation, ValueError):
        whole = 0
    grouped = f"{whole:,}"
    if locale != "en":
        grouped = grouped.replace(",", " ")
    return f"{grouped} {COPY[locale]['currency']}"


def tashkent_time(iso: str) -> str | None:
    """``2026-10-02T13:30:00+00:00`` as ``02.10.2026 18:30`` in Tashkent; ``None`` if bad."""
    try:
        at = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at.astimezone(TASHKENT).strftime("%d.%m.%Y %H:%M")
