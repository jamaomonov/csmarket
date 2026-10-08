"""Public short numbers: 8 Crockford chars; top-ups are ``T`` + 7, orders never start with ``T``."""

from __future__ import annotations

import re

import pytest
from csmarket.core.numbers import (
    ALPHABET,
    allocate,
    is_number,
    is_topup_number,
    order_number,
    topup_number,
)

CROCKFORD = re.compile(r"^[0-9ABCDEFGHJKMNPQRSTVWXYZ]{8}$")


def test_order_numbers_are_8_crockford_chars_never_starting_with_t() -> None:
    seen = {order_number() for _ in range(5000)}
    assert all(CROCKFORD.match(n) for n in seen)
    assert not any(n.startswith("T") for n in seen)
    assert len(seen) > 4990  # random, not sequential


def test_topup_numbers_are_t_plus_7() -> None:
    for _ in range(500):
        n = topup_number()
        assert CROCKFORD.match(n)
        assert n.startswith("T")
        assert is_topup_number(n)


def test_classifiers() -> None:
    assert is_number("7K3M9QX2")
    assert not is_topup_number("7K3M9QX2")
    assert is_topup_number("T7K3M9QX")
    for bad in ("", "T", "7k3m9qx2", "7K3M9QXI", "7K3M9QX", "7K3M9QX22", "T7K3M9QU"):
        assert not is_number(bad), bad
        assert not is_topup_number(bad), bad
    for letter in "ILOU":
        assert letter not in ALPHABET


class _FakeDb:
    """Answers ``db.scalar(exists…)`` from a scripted list of 'taken' flags."""

    def __init__(self, taken: list[bool]) -> None:
        self._taken = list(taken)
        self.calls = 0

    async def scalar(self, _stmt: object) -> bool:
        self.calls += 1
        return self._taken.pop(0)


async def test_allocate_returns_the_first_free_candidate() -> None:
    from csmarket.modules.users.models import User

    db = _FakeDb([True, False])
    values = iter(["AAAAAAAA", "BBBBBBBB"])
    got = await allocate(db, User.id, lambda: next(values))  # type: ignore[arg-type]
    assert got == "BBBBBBBB"
    assert db.calls == 2


async def test_allocate_gives_up_after_the_attempts() -> None:
    from csmarket.modules.users.models import User

    db = _FakeDb([True, True, True])
    with pytest.raises(RuntimeError):
        await allocate(db, User.id, lambda: "AAAAAAAA", attempts=3)  # type: ignore[arg-type]
    assert db.calls == 3


def test_sale_numbers_are_s_plus_7_and_orders_never_start_with_s() -> None:
    from csmarket.core.numbers import is_sale_number, sale_number

    for _ in range(200):
        sale, order = sale_number(), order_number()
        assert sale.startswith("S")
        assert is_number(sale)
        assert is_sale_number(sale)
        assert order[0] not in {"S", "T"}
        assert not is_sale_number(order)
