"""One sale's P&L and reconciliation flag (spec 2026-10-13-sales-pnl)."""

from __future__ import annotations

from decimal import Decimal

from csmarket.modules.sales.pnl import PnlRow, bank_fee, flag, sale_pnl

D = Decimal
PCT = D(1)


def _row(**over: object) -> PnlRow:
    base: dict[str, object] = {
        "payout_to": "balance",
        "status": "credited",
        "attention_reason": None,
        "quoted_usd": D(10),
        "amount_usd": D(10),
        "items_uzs": D(100_000),
        "payout_uzs": D(102_000),
        "rate": D(12_000),
        "cbu_rate": D(12_500),
    }
    base.update(over)
    return PnlRow.model_validate(base)


def _card(status: str, **over: object) -> PnlRow:
    values: dict[str, object] = {
        "payout_to": "card",
        "status": "payout",
        "payout_uzs": D(99_000),
        "request_status": status,
        "request_amount_uzs": D(99_000),
        "request_fee_uzs": D(1_000),
    }
    values.update(over)
    return _row(**values)


def test_bank_fee_rounds_up_to_a_whole_som() -> None:
    assert bank_fee(D(99_000), PCT) == D(990)
    assert bank_fee(D(99_050), PCT) == D(991)
    assert bank_fee(D(99_000), D(0)) == D(0)


def test_a_balance_payout_costs_its_face_value_with_the_bonus() -> None:
    p = sale_pnl(_row(), PCT)
    assert p.income_usd == D(10)
    assert p.to_balances_uzs == D(102_000)
    assert p.cost_uzs == D(102_000)
    assert p.cost_usd == D("8.16")  # at the CBU rate, not the cut 12 000


def test_a_paid_card_costs_the_transfer_and_the_bank_fee() -> None:
    p = sale_pnl(_card("paid", request_bank_fee_uzs=D(990)), PCT)
    assert p.to_cards_uzs == D(99_990)
    assert (p.withheld_uzs, p.bank_uzs) == (D(1_000), D(990))
    assert p.cost_uzs == D(99_990)


def test_a_card_paid_before_the_column_uses_the_setting() -> None:
    p = sale_pnl(_card("paid"), D(2))
    assert p.bank_uzs == D(1_980)
    assert p.to_cards_uzs == D(100_980)


def test_a_rejected_card_costs_what_the_balance_got() -> None:
    p = sale_pnl(_card("rejected"), PCT)
    assert p.to_balances_uzs == D(100_000)
    assert p.to_cards_uzs == D(0)
    assert p.cost_uzs == D(100_000)


def test_a_waiting_card_is_to_pay_with_the_expected_fee() -> None:
    for status in ("waiting_hold", "to_pay"):
        p = sale_pnl(_card(status), PCT)
        assert p.to_pay_uzs == D(99_990)
        assert p.cost_uzs == D(99_990)


def test_a_canceled_card_costs_nothing() -> None:
    p = sale_pnl(_card("canceled"), PCT)
    assert p.cost_uzs == D(0)
    assert p.cost_usd == D(0)


def test_a_rollback_after_payout_is_a_loss() -> None:
    p = sale_pnl(_card("paid", attention_reason="rolled_back", request_bank_fee_uzs=D(990)), PCT)
    assert p.income_usd == D(0)
    assert p.cost_uzs == D(99_990)


def test_no_credited_amount_brings_no_income() -> None:
    assert sale_pnl(_row(amount_usd=None), PCT).income_usd == D(0)


def test_no_cbu_snapshot_falls_back_to_the_sale_rate() -> None:
    assert sale_pnl(_row(cbu_rate=None), PCT).cost_usd == D("8.5")


def test_flags() -> None:
    assert flag(_row()) is None
    assert flag(_row(amount_usd=D("9.80"))) == "short"
    assert flag(_row(amount_usd=D("9.90"))) is None
    assert flag(_row(amount_usd=None)) == "missing"
    assert flag(_row(status="hold", amount_usd=None)) is None
    assert flag(_row(attention_reason="late_deposit")) == "reverted"
    assert flag(_row(attention_reason="rolled_back", amount_usd=D(5))) == "reverted"


def test_income_in_som_is_the_credit_at_the_cbu_rate() -> None:
    p = sale_pnl(_row(cbu_rate=D("12650.5")), PCT)
    assert p.income_uzs == D(126_505)


def test_a_rollback_brings_no_income_in_som_either() -> None:
    assert sale_pnl(_row(attention_reason="rolled_back"), PCT).income_uzs == 0
