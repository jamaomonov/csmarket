from decimal import Decimal

from csmarket.core.money import wire_usd


def test_wire_usd_three_decimals() -> None:
    assert wire_usd(12_345) == "12.345"
    assert wire_usd(Decimal(1000)) == "1.000"
    assert wire_usd(5) == "0.005"
    assert wire_usd(0) == "0.000"
    assert wire_usd(-500) == "-0.500"
