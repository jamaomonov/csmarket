"""Payme (Merchant API) gateway: the ``checkout.paycom.uz`` link for a top-up.

Payme's checkout is a GET URL carrying a base64, ``;``-delimited parameter string; no API
call happens at intent time. The money moves later through Payme's JSON-RPC calls to
``/payments/payme/merchant`` (module ``payme``). Payme speaks **tiyin** (1 soʻm = 100).
``ac.order`` is the top-up number; Payme sends it back as ``params.account.order`` (R9).
Payme has no merchant-initiated refund: a refund is a ``CancelTransaction`` from its cabinet.
"""

from __future__ import annotations

import base64

from csmarket.core.config import get_settings
from csmarket.modules.payments.gateways.base import return_url
from csmarket.modules.payments.payable import Payable


class PaymeGateway:
    """The Payme hosted checkout for our one Payme cash register."""

    provider = "payme"

    @property
    def available(self) -> bool:
        """With the merchant id and a usable key (``Settings.payme_keys()``).

        The sandbox key counts in prod only with ``kassa_sandbox_enabled``.
        """
        s = get_settings()
        return bool(s.payme_merchant_id and s.payme_keys())

    def intent_url(self, *, payable: Payable, locale: str) -> str:
        """``{payme_checkout_url}/{base64("m=<id>;ac.order=<number>;a=<tiyin>;c=<back>;l=<locale>")}``.

        Raises:
            ValueError: ``locale`` is not ``ru``, ``uz`` or ``en``.
        """
        s = get_settings()
        params = (
            f"m={s.payme_merchant_id};ac.order={payable.number};"
            f"a={int(payable.amount_uzs * 100)};c={return_url(payable.number, locale)};l={locale}"
        )
        encoded = base64.b64encode(params.encode()).decode()
        return f"{s.payme_checkout_url.rstrip('/')}/{encoded}"


__all__ = ["PaymeGateway"]
