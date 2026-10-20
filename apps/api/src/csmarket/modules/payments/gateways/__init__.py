"""Payment gateways: the registry of kassas a top-up or an order can be paid through.

The registry is built on first use; whether a gateway is offered is decided per call by
its ``available`` (credentials in settings, or "not prod" for ``mock``). Tasks adding a
kassa register its gateway in :func:`registry`.
"""

from __future__ import annotations

from functools import cache

from csmarket.core.errors import NotFoundError
from csmarket.modules.payments.gateways.base import PaymentGateway, return_url

#: Kassas that only take balance top-ups, never an order (P2P, spec 2026-10-19-p2p-topup).
TOPUP_ONLY = frozenset({"p2p"})

#: The order the storefront offers providers in (owner 2026-10-20: Payme first).
_ORDER = ("payme", "click", "uzum", "p2p", "mock")


@cache
def registry() -> dict[str, PaymentGateway]:
    """Every gateway this build knows, by provider slug (available or not)."""
    from csmarket.modules.payments.gateways.click import ClickGateway
    from csmarket.modules.payments.gateways.mock import MockGateway
    from csmarket.modules.payments.gateways.p2p import P2PGateway
    from csmarket.modules.payments.gateways.payme import PaymeGateway
    from csmarket.modules.payments.gateways.uzum import UzumGateway

    gateways: list[PaymentGateway] = [
        ClickGateway(),
        PaymeGateway(),
        UzumGateway(),
        MockGateway(),
        P2PGateway(),
    ]
    return {gateway.provider: gateway for gateway in gateways}


def available_providers() -> list[str]:
    """Slugs of the gateways that can take payments now, in ``payme, click, uzum, p2p, mock``
    order (owner 2026-10-20)."""
    known = registry()
    return [slug for slug in _ORDER if slug in known and known[slug].available]


def known_kassas() -> list[str]:
    """Every real kassa this build knows (not the dev ``mock``), available or not, in order:
    one without credentials yet can still be shown greyed under maintenance."""
    known = registry()
    return [slug for slug in _ORDER if slug in known and slug != "mock"]


def get_gateway(provider: str) -> PaymentGateway:
    """The gateway for ``provider``.

    Raises:
        NotFoundError: no such gateway, or it is not available here.
    """
    gateway = registry().get(provider)
    if gateway is None or not gateway.available:
        raise NotFoundError("payment provider not available", provider=provider)
    return gateway


__all__ = [
    "PaymentGateway",
    "available_providers",
    "get_gateway",
    "known_kassas",
    "registry",
    "return_url",
]
