"""The closed sets that several modules spell out must stay the same set."""

from __future__ import annotations

from typing import get_args

from csmarket.core import metrics
from csmarket.core.metrics import OrderRefundReason
from csmarket.modules.orders.models import FAILURE_REASONS
from csmarket.modules.orders.schemas import PayProvider
from csmarket.modules.wallet.purchases import REFUND_SOURCES


def test_refund_reasons_match_the_failure_reasons_and_the_metric_labels() -> None:
    labels = metrics._ORDER_REFUND_REASONS  # the private label set, pinned on purpose
    assert set(FAILURE_REASONS) == set(get_args(OrderRefundReason)) == labels


def test_every_way_to_pay_an_order_can_be_refunded() -> None:
    assert set(get_args(PayProvider)) == REFUND_SOURCES
