"""The migration chain and the ORM metadata describe the same schema."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from csmarket.core.db import metadata
from sqlalchemy import inspect, text

pytestmark = pytest.mark.asyncio


async def test_head_matches_models(db_engine) -> None:
    def _diff(sync_conn) -> list[object]:
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(ctx, metadata)

    async with db_engine.connect() as conn:
        diff = await conn.run_sync(_diff)
    assert diff == [], f"models and migrations disagree: {diff}"


async def test_extensions_are_installed(db_engine) -> None:
    async with db_engine.connect() as conn:
        rows = await conn.execute(text("SELECT extname FROM pg_extension"))
        names = {r[0] for r in rows}
    assert {"pgcrypto", "citext", "pg_trgm", "btree_gin"} <= names


async def test_idempotent_responses_exists_with_its_unique_key(db_engine) -> None:
    def _uniques(sync_conn) -> list[str]:
        return [
            u["name"] for u in inspect(sync_conn).get_unique_constraints("idempotent_responses")
        ]

    async with db_engine.connect() as conn:
        names = await conn.run_sync(_uniques)
    assert "uq_idempotent_responses_scope_key" in names


async def test_payments_number_index_serves_a_prefix_search(db_engine) -> None:
    """``ix_payments_number`` uses ``text_pattern_ops``: the admin search's ``LIKE 'T7K%'``
    can use it whatever the database collation."""
    async with db_engine.connect() as conn:
        indexdef = await conn.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_payments_number'")
        )
        assert indexdef is not None
        assert "text_pattern_ops" in indexdef
        await conn.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in await conn.execute(
                text("EXPLAIN SELECT id FROM payments WHERE number LIKE 'T7K%'")
            )
        )
        await conn.rollback()
    assert "ix_payments_number" in plan
