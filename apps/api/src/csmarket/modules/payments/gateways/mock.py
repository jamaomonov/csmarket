"""The dev ``mock`` gateway (ruling R11) — never available in production.

Its intent URL is the payable's own storefront page (a top-up's or an order's) with
``?mock=1``; the page completes the payment through the dev-only pay route, which drives the
real ``hooks.settle``.
"""

from __future__ import annotations

from csmarket.core.config import get_settings
from csmarket.modules.payments.gateways.base import return_url
from csmarket.modules.payments.payable import Payable


class MockGateway:
    """A gateway with no kassa behind it, for local work and e2e."""

    provider = "mock"

    @property
    def available(self) -> bool:
        """Everywhere but production."""
        return not get_settings().is_prod

    def intent_url(self, *, payable: Payable, locale: str) -> str:
        """The payable's status page (top-up or order), flagged ``?mock=1``."""
        return f"{return_url(payable.number, locale)}?mock=1"


__all__ = ["MockGateway"]
