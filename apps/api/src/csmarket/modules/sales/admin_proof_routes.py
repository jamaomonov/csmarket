"""``/api/v1/admin/sales/payouts/{id}/proofs*`` — «Подтверждение оплаты» (ADR-0024).

Admin only. The upload is the file itself as the body (any ``Content-Type``; the type is read
from the bytes), its name percent-encoded in ``X-File-Name``, so no multipart parser is
needed. The body is read in chunks and refused past 5 MB before it is all in memory (the
edge lets 6 MB through on this path only, ``infra/caddy/Caddyfile.prod``). Writes take an
``Idempotency-Key``; the replay keeps the file's SHA-256, never its bytes. Answers are the
request's page, like every other payout write.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated, Any
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.uploads import read_capped_body
from csmarket.modules.admin.api import record, remember, replayed, require_admin, required_key
from csmarket.modules.sales.admin_payouts import payout_detail
from csmarket.modules.sales.admin_proofs import MAX_BYTES, add_proof, delete_proof, read_proof
from csmarket.modules.sales.admin_schemas import PayoutDetailOut
from csmarket.modules.users.api import User

router = APIRouter(
    prefix="/admin/sales/payouts", tags=["admin"], dependencies=[Depends(require_admin)]
)

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]

_UPLOAD_BODY: dict[str, Any] = {  # an OpenAPI fragment
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


async def _finish(
    db: AsyncSession, rid: str, *, scope: str, key: str, request: dict[str, Any]
) -> PayoutDetailOut:
    detail = await payout_detail(db, rid)
    await remember(
        db, scope=scope, key=key, request=request, response=detail.model_dump(mode="json")
    )
    await db.commit()
    return detail


@router.post(
    "/{request_id}/proofs",
    response_model=PayoutDetailOut,
    responses={
        409: {"description": "`payout_not_paid`, `proof_limit` or `idempotency_mismatch`"},
        422: {"description": "`proof_empty`, `proof_too_large` (over 5 MB) or `proof_type`"},
    },
    openapi_extra=_UPLOAD_BODY,
    summary="Attach a payment receipt",
)
async def post_proof(
    request_id: uuid.UUID,
    request: Request,
    *,
    admin: Admin,
    db: Db,
    key: Key,
    x_file_name: Annotated[str | None, Header(max_length=1024)] = None,
) -> PayoutDetailOut:
    """A screenshot or a PDF of the transfer (JPG, PNG, WebP, PDF; 5 MB), to a paid payout,
    three at most. Audited ``sales.payout.proof.add`` (no name, no bytes)."""
    rid, scope = str(request_id), "admin.sales.payout.proof.add"
    data = await read_capped_body(request, max_bytes=MAX_BYTES, too_large_code="proof_too_large")
    name = unquote(x_file_name) if x_file_name else None
    replay = {"id": rid, "sha256": hashlib.sha256(data).hexdigest(), "name": name}
    if (hit := await replayed(db, scope=scope, key=key, request=replay)) is not None:
        return PayoutDetailOut.model_validate(hit)
    proof = await add_proof(db, request_id=rid, admin_id=admin.id, data=data, name=name)
    await record(
        db,
        actor_id=admin.id,
        action="sales.payout.proof.add",
        target_type="payout_request",
        target_id=rid,
        payload={"proof_id": proof.id, "content_type": proof.content_type, "size": proof.size},
    )
    return await _finish(db, rid, scope=scope, key=key, request=replay)


@router.get(
    "/{request_id}/proofs/{proof_id}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The file"}},
    summary="A payment receipt",
)
async def get_proof(request_id: uuid.UUID, proof_id: uuid.UUID, db: Db) -> Response:
    """The receipt's bytes with its sniffed type; never cached."""
    proof = await read_proof(db, request_id=str(request_id), proof_id=str(proof_id))
    return Response(
        content=proof.data,
        media_type=proof.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(proof.name)}",
        },
    )


@router.delete(
    "/{request_id}/proofs/{proof_id}",
    response_model=PayoutDetailOut,
    responses={409: {"description": "`proof_delete_expired` or `idempotency_mismatch`"}},
    summary="Delete a receipt uploaded minutes ago",
)
async def delete_proof_route(
    request_id: uuid.UUID, proof_id: uuid.UUID, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """Within 10 minutes of its upload; after that the receipt stays. Audited
    ``sales.payout.proof.delete``."""
    rid, pid, scope = str(request_id), str(proof_id), "admin.sales.payout.proof.delete"
    replay = {"id": rid, "proof_id": pid}
    if (hit := await replayed(db, scope=scope, key=key, request=replay)) is not None:
        return PayoutDetailOut.model_validate(hit)
    proof = await delete_proof(db, request_id=rid, proof_id=pid)
    await record(
        db,
        actor_id=admin.id,
        action="sales.payout.proof.delete",
        target_type="payout_request",
        target_id=rid,
        payload={"proof_id": pid, "content_type": proof.content_type, "size": proof.size},
    )
    return await _finish(db, rid, scope=scope, key=key, request=replay)


__all__ = ["router"]
