"""«Подтверждение оплаты»: receipts an admin attaches to a paid payout (ADR-0024).

Up to :data:`MAX_PROOFS` files of at most :data:`MAX_BYTES` each, only to a ``paid`` request
(409 ``payout_not_paid``); the type is read from the bytes (:func:`sniff`), never from the
client. A receipt may be deleted for :data:`DELETE_WINDOW` after its upload, then it stays for
good — it is the shop's proof in a dispute. Writes lock the request row, so two uploads at once
cannot pass the limit together. Admins only; the seller never sees them. Neither the bytes nor
the name are logged (a receipt may show a card or a name).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.core.uploads import sniff
from csmarket.modules.sales.admin_sales import user_of, users_by_id
from csmarket.modules.sales.admin_schemas import PayoutProofOut
from csmarket.modules.sales.models import PayoutProof, PayoutRequest

#: Receipts per payout.
MAX_PROOFS = 3
#: One receipt's size, bytes (5 MB).
MAX_BYTES = 5 * 1024 * 1024
#: How long a receipt may be deleted after its upload.
DELETE_WINDOW = timedelta(minutes=10)
#: The longest kept name, characters (the column's width).
NAME_LEN = 120

_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf"}
_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\]")


def clean_name(raw: str | None, content_type: str) -> str:
    """The uploaded name without a path, control characters or excess length; a plain
    ``receipt.<ext>`` when nothing is left."""
    name = unicodedata.normalize("NFC", raw or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = _UNSAFE.sub("", name).strip()[:NAME_LEN].strip()
    return name or f"receipt.{_EXT[content_type]}"


def delete_until(proof: PayoutProof, at: datetime | None = None) -> datetime | None:
    """Until when ``proof`` may be deleted; ``None`` once it may not."""
    until = proof.created_at + DELETE_WINDOW
    return until if until > (at or now()) else None


async def proofs_out(db: AsyncSession, request_id: str) -> list[PayoutProofOut]:
    """The request's receipts, oldest first, without their bytes."""
    proofs = (
        await db.scalars(
            select(PayoutProof)
            .where(PayoutProof.request_id == request_id)
            .order_by(PayoutProof.created_at, PayoutProof.id)
        )
    ).all()
    users = await users_by_id(db, [p.uploaded_by for p in proofs if p.uploaded_by])
    at = now()
    return [
        PayoutProofOut(
            id=p.id,
            name=p.name,
            content_type=p.content_type,
            size=p.size,
            uploaded_by=user_of(users, p.uploaded_by) if p.uploaded_by else None,
            created_at=p.created_at,
            delete_until=delete_until(p, at),
        )
        for p in proofs
    ]


async def _locked(db: AsyncSession, request_id: str) -> PayoutRequest:
    request = await db.scalar(
        select(PayoutRequest)
        .where(PayoutRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise NotFoundError("payout request not found")
    return request


async def add_proof(
    db: AsyncSession, *, request_id: str, admin_id: str, data: bytes, name: str | None
) -> PayoutProof:
    """Attach ``data`` to the paid request ``request_id`` and flush.

    Raises:
        NotFoundError: Unknown request.
        ValidationError: ``proof_empty``, ``proof_too_large`` or ``proof_type``.
        ConflictError: ``payout_not_paid`` or ``proof_limit``.
    """
    if not data:
        raise ValidationError("the file is empty", code="proof_empty")
    if len(data) > MAX_BYTES:
        raise ValidationError("the file is larger than 5 MB", code="proof_too_large")
    content_type = sniff(data)
    if content_type is None:
        raise ValidationError("only JPG, PNG, WebP or PDF", code="proof_type")
    request = await _locked(db, request_id)
    if request.status != "paid":
        raise ConflictError("only a paid payout takes receipts", code="payout_not_paid")
    count = await db.scalar(
        select(func.count()).select_from(PayoutProof).where(PayoutProof.request_id == request_id)
    )
    if (count or 0) >= MAX_PROOFS:
        raise ConflictError(f"at most {MAX_PROOFS} receipts per payout", code="proof_limit")
    proof = PayoutProof(
        request_id=request_id,
        name=clean_name(name, content_type),
        content_type=content_type,
        size=len(data),
        data=data,
        uploaded_by=admin_id,
    )
    db.add(proof)
    await db.flush()
    return proof


async def _proof(db: AsyncSession, request_id: str, proof_id: str, *, data: bool) -> PayoutProof:
    query = select(PayoutProof).where(
        PayoutProof.id == proof_id, PayoutProof.request_id == request_id
    )
    if data:
        query = query.options(undefer(PayoutProof.data))
    proof = await db.scalar(query)
    if proof is None:
        raise NotFoundError("receipt not found")
    return proof


async def read_proof(db: AsyncSession, *, request_id: str, proof_id: str) -> PayoutProof:
    """The receipt with its bytes.

    Raises:
        NotFoundError: Unknown, or another request's.
    """
    return await _proof(db, request_id, proof_id, data=True)


async def delete_proof(db: AsyncSession, *, request_id: str, proof_id: str) -> PayoutProof:
    """Delete a receipt uploaded in the last :data:`DELETE_WINDOW` and flush.

    Raises:
        NotFoundError: Unknown, or another request's.
        ConflictError: ``proof_delete_expired``.
    """
    await _locked(db, request_id)
    proof = await _proof(db, request_id, proof_id, data=False)
    if delete_until(proof) is None:
        raise ConflictError(
            "a receipt may be deleted for 10 minutes only", code="proof_delete_expired"
        )
    await db.delete(proof)
    await db.flush()
    return proof


__all__ = [
    "DELETE_WINDOW",
    "MAX_BYTES",
    "MAX_PROOFS",
    "add_proof",
    "clean_name",
    "delete_proof",
    "delete_until",
    "proofs_out",
    "read_proof",
]
