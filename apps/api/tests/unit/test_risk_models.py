"""The risk tables and the new statuses (spec 2026-10-21-payment-risk-limits)."""

from csmarket.modules.orders.fsm import TRANSITIONS
from csmarket.modules.orders.models import ON_REVIEW, ORDER_STATUSES
from csmarket.modules.payments.models import TOPUP_STATUSES
from csmarket.modules.risk.models import HOLD_DECISIONS, HOLD_REASONS, PaymentHold


def test_new_statuses_exist() -> None:
    assert "held" in TOPUP_STATUSES
    assert "rejected" in TOPUP_STATUSES
    assert "held" in ORDER_STATUSES
    assert frozenset({"held"}) == ON_REVIEW


def test_order_fsm_holds_and_decides() -> None:
    assert "held" in TRANSITIONS["pending"]
    assert TRANSITIONS["held"] == frozenset({"paid", "cancelled"})


def test_hold_vocabulary() -> None:
    assert HOLD_REASONS == ("kassa_limit", "user_limit", "check_failed")
    assert HOLD_DECISIONS == ("released", "returned", "reversed_by_kassa")
    assert PaymentHold.__tablename__ == "payment_holds"
