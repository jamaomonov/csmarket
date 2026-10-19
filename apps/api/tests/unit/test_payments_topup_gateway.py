"""Which gateway a new top-up opens in: P2P has none to open (the card details come with the
top-up), the balance is never one, an unknown kassa is refused."""

from __future__ import annotations

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.payments.topups import kassa_for_new_topup


def test_p2p_opens_no_kassa_page() -> None:
    assert kassa_for_new_topup("p2p") is None


@pytest.mark.parametrize("provider", ["wallet", "nope"])
def test_the_balance_and_unknown_kassas_are_refused(provider: str) -> None:
    with pytest.raises(ValidationError):
        kassa_for_new_topup(provider)
