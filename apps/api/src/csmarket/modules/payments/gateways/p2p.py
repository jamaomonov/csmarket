"""The ``p2p`` gateway: a balance top-up by a card transfer (spec 2026-10-19-p2p-topup).

No kassa page: the top-up's response carries the card and the exact amount
(``TopupOut.p2p``), and the ``p2p`` module settles the attempt when the bank's notification
arrives. Top-ups only (``TOPUP_ONLY``); offered while its kassa switch is on.
"""

from __future__ import annotations

from decimal import Decimal

from csmarket.modules.payments.payable import Payable


class P2PGateway:
    """A card transfer; the ``p2p`` module holds the amount and matches the transfer."""

    provider = "p2p"

    @property
    def available(self) -> bool:
        """Always built; whether it is offered is the kassa switch."""
        return True

    def intent_url(self, *, payable: Payable, charge_uzs: Decimal, locale: str) -> str:  # noqa: ARG002 -- no kassa page
        """None to open: an empty URL the top-up flow never hands out for ``p2p``."""
        return ""


__all__ = ["P2PGateway"]
