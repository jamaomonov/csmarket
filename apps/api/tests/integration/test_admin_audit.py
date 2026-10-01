"""``admin.audit.record`` writes one ``admin_audit_log`` row (ruling Q5)."""

from __future__ import annotations

import pytest
from csmarket.modules.admin.audit import record
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.users.api import upsert_user_by_steam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_record_writes_one_row(db_session: AsyncSession) -> None:
    admin = await upsert_user_by_steam(
        db_session, steam_id="76561198000000001", display_name="Owner", avatar_url=None
    )
    await record(
        db_session,
        actor_id=admin.id,
        action="skins.item.hide",
        target_type="skin_item",
        target_id="x",
        payload={"slug": "ak"},
    )
    await db_session.commit()
    row = (await db_session.execute(select(AdminAuditLog))).scalar_one()
    assert (row.action, row.target_type, row.target_id, row.payload) == (
        "skins.item.hide",
        "skin_item",
        "x",
        {"slug": "ak"},
    )
    assert row.actor_user_id == admin.id
    assert row.created_at is not None


async def test_record_without_payload_stores_an_empty_object(db_session: AsyncSession) -> None:
    admin = await upsert_user_by_steam(
        db_session, steam_id="76561198000000001", display_name=None, avatar_url=None
    )
    await record(
        db_session, actor_id=admin.id, action="skins.alias.delete", target_type="t", target_id="a"
    )
    await db_session.commit()
    assert (await db_session.execute(select(AdminAuditLog))).scalar_one().payload == {}
