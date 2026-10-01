"""``GET /api/v1/admin/audit`` — who did what, newest first. Admin only, read-only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.audit_schemas import AuditOut
from csmarket.modules.admin.audit_service import list_audit
from csmarket.modules.admin.deps import require_admin

router = APIRouter(prefix="/admin/audit", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
_Filter = Query(max_length=64)


@router.get("", response_model=AuditOut, summary="The audit log")
async def get_audit(
    db: Db,
    *,
    action: Annotated[str | None, _Filter] = None,
    target_type: Annotated[str | None, _Filter] = None,
    target_id: Annotated[str | None, _Filter] = None,
    actor_id: Annotated[str | None, _Filter] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AuditOut:
    """Newest first; each filter is an exact match and they combine with AND."""
    items, next_cursor = await list_audit(
        db,
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_id=actor_id,
        cursor=cursor,
        limit=limit,
    )
    return AuditOut(items=items, next_cursor=next_cursor)


__all__ = ["router"]
