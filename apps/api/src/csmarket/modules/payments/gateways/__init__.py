"""Payment gateways: the registry of kassas a top-up can be paid through.

The registry is built on first use; whether a gateway is offered is decided per call by
its ``available`` (credentials in settings, or "not prod" for ``mock``). Tasks adding a
kassa register its gateway in :func:`registry`.
"""

from __future__ import annotations

from functools import cache

from csmarket.core.errors import NotFoundError
from csmarket.modules.payments.gateways.base import PaymentGateway, return_url

#: The order the storefront offers providers in.
_ORDER = ("click", "payme", "uzum", "mock")


@cache
def registry() -> dict[str, PaymentGateway]:
    """Every gateway this build knows, by provider slug (available or not)."""
    from csmarket.modules.payments.gateways.click import ClickGateway
    from csmarket.modules.payments.gateways.mock import MockGateway
    from csmarket.modules.payments.gateways.payme import PaymeGateway

    gateways: list[PaymentGateway] = [ClickGateway(), PaymeGateway(), MockGateway()]
    return {gateway.provider: gateway for gateway in gateways}


def available_providers() -> list[str]:
    """Slugs of the gateways that can take payments now, in ``click, payme, uzum, mock`` order."""
    known = registry()
    return [slug for slug in _ORDER if slug in known and known[slug].available]


def get_gateway(provider: str) -> PaymentGateway:
    """The gateway for ``provider``.

    Raises:
        NotFoundError: no such gateway, or it is not available here.
    """
    gateway = registry().get(provider)
    if gateway is None or not gateway.available:
        raise NotFoundError("payment provider not available", provider=provider)
    return gateway


__all__ = ["PaymentGateway", "available_providers", "get_gateway", "registry", "return_url"]
