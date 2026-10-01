"""Click Shop API ``sign_string``: build (prepare / complete) and verify.

Click signs every callback with an MD5 over the **raw wire strings** and the service's
``SECRET_KEY``; nothing here may reformat a value (``"1000.00"`` and ``"1000"`` hash
differently). Pure apart from reading the one configured service and secret. The sign
string and the secret are never logged.

- prepare: ``md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + amount +
  action + sign_time)``
- complete: the same with ``merchant_prepare_id`` right after ``merchant_trans_id``.
"""

from __future__ import annotations

import hashlib
import hmac

from csmarket.core.config import get_settings


def secret_for_service(service_id: int) -> str | None:
    """The ``SECRET_KEY`` for ``service_id``: ours only for our one configured service.

    Returns:
        ``click_secret_key`` when ``service_id`` is ``click_service_id`` and the secret is
        set; ``None`` otherwise (another service, Click unconfigured, or a blank secret —
        a half-configured service never verifies against an empty key).
    """
    settings = get_settings()
    if settings.click_service_id is None or service_id != settings.click_service_id:
        return None
    return settings.click_secret_key or None


def _md5(*parts: str) -> str:
    # MD5 is Click's signature scheme, not our choice; it authenticates their callback only.
    return hashlib.md5("".join(parts).encode()).hexdigest()  # noqa: S324


def prepare_sign(
    *,
    click_trans_id: str,
    service_id: str,
    secret: str,
    merchant_trans_id: str,
    amount: str,
    action: str,
    sign_time: str,
) -> str:
    """The lowercase hex MD5 Click sends with ``/prepare``; every value as received."""
    return _md5(click_trans_id, service_id, secret, merchant_trans_id, amount, action, sign_time)


def complete_sign(
    *,
    click_trans_id: str,
    service_id: str,
    secret: str,
    merchant_trans_id: str,
    merchant_prepare_id: str,
    amount: str,
    action: str,
    sign_time: str,
) -> str:
    """The lowercase hex MD5 Click sends with ``/complete``; every value as received."""
    return _md5(
        click_trans_id,
        service_id,
        secret,
        merchant_trans_id,
        merchant_prepare_id,
        amount,
        action,
        sign_time,
    )


def verify(expected_hex: str, received: str) -> bool:
    """Constant-time, case-insensitive compare of ``received`` (whitespace-stripped).

    Fails closed: a non-ASCII ``received`` (``compare_digest`` raises ``TypeError`` on it)
    is a mismatch, never an exception that would break the always-200 contract.
    """
    try:
        return hmac.compare_digest(expected_hex.lower(), received.strip().lower())
    except TypeError:
        return False


__all__ = ["complete_sign", "prepare_sign", "secret_for_service", "verify"]
