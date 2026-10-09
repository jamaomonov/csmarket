"""A key's IP allow-list as the user sets it (spec v1.1 section 4)."""

from __future__ import annotations

import ipaddress

from csmarket.core.errors import ValidationError

#: Entries a key may carry.
MAX_ENTRIES = 20
#: The longest canonical IPv6 network (the column width).
MAX_LENGTH = 43


def _canonical(raw: str) -> str | None:
    """The canonical network, or ``None`` for a scoped IPv6, a bad entry or an over-long form."""
    if "%" in raw:  # a scoped IPv6 address means nothing off its host
        return None
    try:
        net = str(ipaddress.ip_network(raw.strip(), strict=False))
    except ValueError:
        return None
    return net if len(net) <= MAX_LENGTH else None


def normalise(entries: list[str]) -> list[str]:
    """Networks in canonical form, first occurrence kept; ``[]`` means any address.

    Args:
        entries: IPv4 / IPv6 addresses or CIDR networks, as typed.

    Returns:
        The distinct networks, host bits cleared (``10.1.2.3/8`` becomes ``10.0.0.0/8``).

    Raises:
        ValidationError: ``ip_allowlist_invalid`` with the ``index`` of the bad entry.
    """
    out: list[str] = []
    for index, raw in enumerate(entries):
        if index >= MAX_ENTRIES:
            raise ValidationError("too many addresses", code="ip_allowlist_invalid", index=index)
        net = _canonical(raw)
        if net is None:
            raise ValidationError(
                "not an IP address or network", code="ip_allowlist_invalid", index=index
            )
        if net not in out:
            out.append(net)
    return out
