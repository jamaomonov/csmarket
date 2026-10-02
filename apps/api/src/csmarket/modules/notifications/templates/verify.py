"""``verify``: confirm the address before order letters go to it (decision D1)."""

from __future__ import annotations

from csmarket.modules.notifications.copy import COPY
from csmarket.modules.notifications.templates.base import EmailContent, Links, Locale, compose


def build(*, locale: Locale, links: Links) -> EmailContent:
    """The confirmation letter; the link is ``links.confirm_url``."""
    words = COPY[locale]
    return compose(
        locale=locale,
        subject=words["verify.subject"],
        body=words["verify.body"],
        href=links.confirm_url,
        label=words["button.verify"],
        links=links,
    )
