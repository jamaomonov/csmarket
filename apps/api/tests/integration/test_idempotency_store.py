"""The generic replay store: first write wins, repeat reads it back, races are swallowed."""

from __future__ import annotations

import pytest
from csmarket.core.idempotency import load_replay, save_replay
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_miss_then_hit(db_session: AsyncSession) -> None:
    assert await load_replay(db_session, scope="t.retry", idempotency_key="k" * 16) is None
    await save_replay(
        db_session, scope="t.retry", idempotency_key="k" * 16, body={"ok": True}, status_code=202
    )
    await db_session.commit()
    hit = await load_replay(db_session, scope="t.retry", idempotency_key="k" * 16)
    assert hit is not None
    assert (hit.status_code, hit.body) == (202, {"ok": True})


async def test_same_key_in_another_scope_is_a_miss(db_session: AsyncSession) -> None:
    await save_replay(db_session, scope="a", idempotency_key="k" * 16, body=None)
    await db_session.commit()
    assert await load_replay(db_session, scope="b", idempotency_key="k" * 16) is None


async def test_a_duplicate_save_keeps_the_first_response(db_session: AsyncSession) -> None:
    await save_replay(db_session, scope="a", idempotency_key="k" * 16, body={"n": 1})
    await save_replay(db_session, scope="a", idempotency_key="k" * 16, body={"n": 2})
    await db_session.commit()
    hit = await load_replay(db_session, scope="a", idempotency_key="k" * 16)
    assert hit is not None
    assert hit.body == {"n": 1}
