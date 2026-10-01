"""Symmetric encryption for application secrets at rest, parameterised by purpose.

XSalsa20-Poly1305 via ``nacl.secret.SecretBox``, one random nonce per row.

## Key material

There is one input key -- ``CSMARKET_APP_ENC_KEY`` -- and every purpose gets its own
HKDF-derived key from it, domain-separated by an ``info`` label. Purpose labels are
declared by the module that owns the secret and are versioned: changing the cipher or
the encoding means a new label, not a silent reinterpretation of existing rows.
Compromising one purpose's key does not hand over another's.

## What this does and does not buy

A database dump alone yields nothing usable -- ciphertext without the key is inert. An
attacker who holds **both** the dump and the application key is exactly as well off as
if the secret were stored in the clear. That is the honest boundary: this defends
against a stolen backup, a leaked replica, or a SQL-injection read, not against a
compromised application host.

Dev and test derive a deterministic key so the suite needs no extra setup; production
with an empty key **raises at first use** rather than silently encrypting under a
guessable key.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.secret import SecretBox

from csmarket.core.config import Settings, get_settings

#: Nonce width, re-exported so callers need not import nacl to size a column.
NONCE_SIZE = SecretBox.NONCE_SIZE


def _derive_dev_key(seed: str) -> bytes:
    """Deterministic dev/test key. Never reached when ``is_prod``."""
    return hashlib.sha256(("csmarket-dev:" + seed).encode("utf-8")).digest()


def input_key_material(settings: Settings) -> bytes:
    """The raw 32-byte input key every purpose is derived from.

    Args:
        settings: The app settings to read ``CSMARKET_APP_ENC_KEY`` from.

    Returns:
        32 bytes of input key material.

    Raises:
        RuntimeError: In production with no key configured, or when the
            configured value is not 32 bytes of base64.
    """
    raw = settings.app_enc_key or ""
    if not raw:
        if settings.is_prod:
            raise RuntimeError(
                "CSMARKET_APP_ENC_KEY is required in production -- refusing to start."
            )
        return _derive_dev_key(settings.environment)
    # Accept either urlsafe or standard base64; tolerate missing padding.
    cleaned = raw.strip().replace("-", "+").replace("_", "/")
    padding = "=" * (-len(cleaned) % 4)
    try:
        key = base64.b64decode(cleaned + padding, validate=False)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise RuntimeError("CSMARKET_APP_ENC_KEY is not valid base64") from exc
    if len(key) != SecretBox.KEY_SIZE:
        raise RuntimeError(
            f"CSMARKET_APP_ENC_KEY must decode to {SecretBox.KEY_SIZE} bytes; got {len(key)}"
        )
    return key


def derive_key(ikm: bytes, purpose: str) -> bytes:
    """HKDF-SHA256 a purpose-specific key from the input key material.

    Args:
        ikm: The input key material from :func:`input_key_material`.
        purpose: The domain-separation label, e.g. ``"csmarket:tradelink:v1"``.

    Returns:
        A 32-byte key independent of every other purpose's.
    """
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=purpose.encode("utf-8"))
    return hkdf.derive(ikm)


@lru_cache(maxsize=8)
def box_for(purpose: str) -> SecretBox:
    """The cached ``SecretBox`` for one purpose.

    Args:
        purpose: The domain-separation label.

    Returns:
        A box keyed by this purpose's derived key.
    """
    return SecretBox(derive_key(input_key_material(get_settings()), purpose))


def encrypt(plaintext: str, *, purpose: str) -> tuple[bytes, bytes]:
    """Encrypt a secret under ``purpose``'s key.

    Args:
        plaintext: The secret. UTF-8 encoded before encryption.
        purpose: The domain-separation label.

    Returns:
        ``(ciphertext, nonce)``. The nonce is stored beside the ciphertext,
        not prepended to it.
    """
    nonce = secrets.token_bytes(SecretBox.NONCE_SIZE)
    # ``SecretBox.encrypt`` returns nonce + ciphertext; we store them in
    # separate columns, so peel off the ciphertext-with-MAC part.
    return box_for(purpose).encrypt(plaintext.encode("utf-8"), nonce).ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes, *, purpose: str) -> str:
    """Decrypt a secret encrypted under ``purpose``'s key.

    Args:
        ciphertext: The stored ciphertext (with its Poly1305 tag).
        nonce: The stored nonce.
        purpose: The domain-separation label used at encryption time.

    Returns:
        The plaintext secret.

    Raises:
        nacl.exceptions.CryptoError: If the key is wrong or the row was
            tampered with -- the MAC is what makes that detectable.
    """
    return box_for(purpose).decrypt(ciphertext, nonce).decode("utf-8")


__all__ = [
    "NONCE_SIZE",
    "box_for",
    "decrypt",
    "derive_key",
    "encrypt",
    "input_key_material",
]
