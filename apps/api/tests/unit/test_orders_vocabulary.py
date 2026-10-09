"""The closed sets that several modules spell out must stay the same set."""

from __future__ import annotations

from typing import get_args

from csmarket.core import metrics
from csmarket.core.metrics import OrderRefundReason, TradeAttentionReason
from csmarket.modules.orders.models import ATTENTION_REASONS, FAILURE_REASONS
from csmarket.modules.orders.schemas import PayProvider
from csmarket.modules.wallet.purchases import REFUND_SOURCES, USD_WALLET


def test_refund_reasons_match_the_failure_reasons_and_the_metric_labels() -> None:
    labels = metrics._ORDER_REFUND_REASONS  # the private label set, pinned on purpose
    assert set(FAILURE_REASONS) == set(get_args(OrderRefundReason)) == labels


def test_every_way_to_pay_an_order_can_be_refunded() -> None:
    # ``usd_wallet`` is how API orders are paid: no pay endpoint, but refundable.
    assert set(get_args(PayProvider)) | {USD_WALLET} == REFUND_SOURCES


def test_attention_reasons_match_the_metric_labels() -> None:
    labels = metrics._TRADE_ATTENTION_REASONS  # the private label set, pinned on purpose
    assert set(ATTENTION_REASONS) == set(get_args(TradeAttentionReason)) == labels
