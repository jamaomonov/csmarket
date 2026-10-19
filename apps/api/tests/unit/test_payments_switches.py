"""Kassa switches (spec 2026-10-19-p2p-topup): on, maintenance or off per kassa."""

from __future__ import annotations

import pytest
from csmarket.modules.payments.fees import KassaFees
from pydantic import ValidationError


def test_a_kassa_is_on_unless_switched_and_p2p_starts_off() -> None:
    fees = KassaFees()
    assert fees.status("click") == "on"
    assert fees.status("p2p") == "off"


def test_a_saved_status_wins() -> None:
    fees = KassaFees(statuses={"payme": "maintenance", "p2p": "on"})
    assert fees.status("payme") == "maintenance"
    assert fees.status("p2p") == "on"


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(ValidationError):
        KassaFees.model_validate({"statuses": {"click": "paused"}})
