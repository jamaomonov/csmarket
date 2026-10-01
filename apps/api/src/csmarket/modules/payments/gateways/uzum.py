"""Uzum (Merchant API) gateway: the ``uzumbank.uz/open-service`` link for a top-up.

Uzum's checkout is a GET deep link; no API call happens at intent time. The money moves
later through Uzum's five calls to ``/payments/uzum/*`` (module ``uzum``). The link carries
no amount: Uzum's app prefills it from our ``/check`` answer (``data.amount.value``, soʻm).
``order`` is the top-up number; Uzum sends it back as ``params.order`` (R9). Uzum has no
merchant-initiated refund: a refund is Uzum calling ``/reverse``.
"""

from __future__ import annotations

from urllib.parse import urlencode

from csmarket.core.config import get_settings
from csmarket.modules.payments.gateways.base import return_url
from csmarket.modules.payments.payable import Payable


class UzumGateway:
    """The Uzum open-service checkout for our one Uzum service."""

    provider = "uzum"

    @property
    def available(self) -> bool:
        """With the service id and a whole usable login/password pair (``Settings.uzum_pairs()``).

        The sandbox pair counts in prod only with ``kassa_sandbox_enabled``.
        """
        s = get_settings()
        return bool(s.uzum_service_id and s.uzum_pairs())

    def intent_url(self, *, payable: Payable, locale: str) -> str:
        """``{uzum_open_service_url}?serviceId=<id>&order=<number>&redirectUrl=<our page>``.

        Raises:
            ValueError: ``locale`` is not ``ru``, ``uz`` or ``en``.
        """
        s = get_settings()
        query = urlencode(
            {
                "serviceId": s.uzum_service_id,
                "order": payable.number,
                "redirectUrl": return_url(payable.number, locale),
            }
        )
        return f"{s.uzum_open_service_url}?{query}"


__all__ = ["UzumGateway"]
