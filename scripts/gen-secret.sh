#!/usr/bin/env bash
# Helper to generate fresh credentials. Usage: ./scripts/gen-secret.sh <kind>
set -euo pipefail

kind="${1:?usage: $0 <jwt|pg|redis|generic>}"

case "$kind" in
  jwt)
    echo "Generating Ed25519 keypair (base64)…"
    python3 - <<'PY'
import base64
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
sk = Ed25519PrivateKey.generate()
print("JWT_PRIVATE_KEY (PEM):"); print(sk.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()).decode())
pub = sk.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo)
print("JWT_PUBLIC_KEY (PEM):"); print(pub.decode())
priv = sk.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption())
print("# base64 one-liners for secrets/api.env:")
print("CSMARKET_JWT_PRIVATE_KEY=" + base64.b64encode(priv).decode())
print("CSMARKET_JWT_PUBLIC_KEY=" + base64.b64encode(pub).decode())
PY
    ;;
  pg|redis|generic)
    openssl rand -base64 32 | tr -d '\n'; echo
    ;;
  *)
    echo "Unknown kind: $kind" >&2
    exit 2
    ;;
esac
