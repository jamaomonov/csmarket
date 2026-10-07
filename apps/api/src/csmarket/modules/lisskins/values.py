"""Reading LIS-SKINS' JSON values field by field (the client and the export share it)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def decimal_of(value: object) -> Decimal | None:
    """A JSON number (or numeric string) as ``Decimal`` via its text; ``None`` otherwise."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def int_of(value: object) -> int | None:
    """An integer, or a string of digits, as ``int``; ``None`` otherwise."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def str_of(value: object) -> str | None:
    """A non-empty string, or ``None``."""
    return value if isinstance(value, str) and value else None


__all__ = ["decimal_of", "int_of", "str_of"]
