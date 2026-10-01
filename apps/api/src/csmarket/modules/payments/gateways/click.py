"""Click (Shop API) gateway: the ``my.click.uz`` pay link for a top-up.

Click's checkout is a plain GET URL; the money moves later through Click's own callbacks
(``/payments/click/prepare`` and ``/complete``, module ``click``). Click's ``amount`` is
soʻm (major units), unlike Payme's and Uzum's tiyin. ``transaction_param`` is the top-up
number; Click sends it back as ``merchant_trans_id``. Click has no merchant-initiated refund.
"""

from __future__ import annotations

from urllib.parse import urlencode

from csmarket.core.config import get_settings
from csmarket.core.money import wire_uzs
from csmarket.modules.payments.gateways.base import return_url
from csmarket.modules.payments.payable import Payable


class ClickGateway:
    """The Click pay page for our one Click service."""

    provider = "click"

    @property
    def available(self) -> bool:
        """With the merchant id, the service id and its ``SECRET_KEY`` all set."""
        s = get_settings()
        return bool(s.click_merchant_id and s.click_service_id and s.click_secret_key)

    def intent_url(self, *, payable: Payable, locale: str) -> str:
        """``{click_pay_url}?service_id=&merchant_id=&amount=&transaction_param=&return_url=``.

        Raises:
            ValueError: ``locale`` is not ``ru``, ``uz`` or ``en``.
        """
        s = get_settings()
        query = {
            "service_id": str(s.click_service_id),
            "merchant_id": str(s.click_merchant_id),
            "amount": wire_uzs(payable.amount_uzs),
            "transaction_param": payable.number,
            "return_url": return_url(payable.number, locale),
        }
        return f"{s.click_pay_url}?{urlencode(query)}"


__all__ = ["ClickGateway"]
