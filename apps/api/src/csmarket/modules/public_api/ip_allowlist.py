"""A key's IP allow-list as the user sets it (spec v1.1 section 4)."""

from __future__ import annotations

import ipaddress

from csmarket.core.errors import ValidationError

#: Entries a key may carry.
MAX_ENTRIES = 20


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
        try:
            net = str(ipaddress.ip_network(raw.strip(), strict=False))
        except ValueError:
            raise ValidationError(
                "not an IP address or network", code="ip_allowlist_invalid", index=index
            ) from None
        if net not in out:
            out.append(net)
    return out
