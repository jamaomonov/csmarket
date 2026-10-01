"""``upsert_items`` is idempotent, updates metadata, and never touches prices."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from csmarket.modules.skins.bymykel import (
    FILES,
    SKINS_FILE,
    CatalogRow,
    dedupe,
    import_catalog,
    rows_from_skins,
    upsert_items,
)
from csmarket.modules.skins.models import SkinItem
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"
BASE = "https://bymykel.test/api/en"


def _rows() -> list[CatalogRow]:
    return dedupe(rows_from_skins(json.loads((FIXTURES / "bymykel_skins.json").read_text())))


async def test_second_import_writes_nothing(db_session: AsyncSession) -> None:
    assert await upsert_items(db_session, _rows()) == 3
    await db_session.commit()
    assert await upsert_items(db_session, _rows()) == 0


async def test_changed_image_is_written_and_prices_and_hidden_survive(
    db_session: AsyncSession,
) -> None:
    await upsert_items(db_session, _rows())
    await db_session.commit()
    row = (
        await db_session.execute(
            select(SkinItem).where(SkinItem.slug == "ak-47-redline-field-tested")
        )
    ).scalar_one()
    row.min_auto_units = 27867
    row.count_auto = 49
    row.active = True
    row.hidden = True
    await db_session.commit()

    from dataclasses import replace

    changed = [
        replace(r, image_url="https://community.akamai.steamstatic.com/economy/image/new")
        if r.slug == "ak-47-redline-field-tested"
        else r
        for r in _rows()
    ]
    assert await upsert_items(db_session, changed) == 1
    await db_session.commit()
    db_session.expire_all()
    row = (
        await db_session.execute(
            select(SkinItem).where(SkinItem.slug == "ak-47-redline-field-tested")
        )
    ).scalar_one()
    assert row.image_url is not None
    assert row.image_url.endswith("/new")
    assert (row.min_auto_units, row.count_auto, row.active) == (27867, 49, True)
    # The row was really rewritten (its image changed), and ``hidden`` still survived.
    assert row.hidden is True


def _mock_upstream(router: respx.MockRouter) -> None:
    """Every ByMykel file answers: the skins fixture, the agents fixture, empty lists else."""
    for key in FILES:
        name = {SKINS_FILE: "bymykel_skins.json", "agents": "bymykel_agents.json"}.get(key)
        body = json.loads((FIXTURES / name).read_text()) if name else []
        router.get(f"{BASE}/{key}.json").respond(200, json=body)


async def _import_fixture(factory: async_sessionmaker[AsyncSession]) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_upstream(router)
        async with httpx.AsyncClient() as http:
            await import_catalog(factory, base_url=BASE, http=http)


async def test_import_catalog_reads_every_file(db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    with respx.mock(assert_all_called=False) as router:
        _mock_upstream(router)
        async with httpx.AsyncClient() as http:
            summary = await import_catalog(factory, base_url=BASE, http=http)
    assert summary.files == len(FILES)
    assert summary.rows == summary.changed == 4  # 3 skins + 1 agent
    async with factory() as db:
        assert (await db.execute(select(func.count()).select_from(SkinItem))).scalar_one() == 4


async def test_import_catalog_fails_on_an_upstream_error(db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    with respx.mock() as router:
        router.get(f"{BASE}/{SKINS_FILE}.json").respond(503)
        async with httpx.AsyncClient() as http:
            with pytest.raises(httpx.HTTPStatusError):
                await import_catalog(factory, base_url=BASE, http=http)


async def test_reimport_keeps_hidden_and_prices(db_session: AsyncSession, db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await _import_fixture(factory)
    item = (await db_session.execute(select(SkinItem).limit(1))).scalar_one()
    item.hidden = True
    item.min_auto_units = 12_345
    await db_session.commit()
    await _import_fixture(factory)
    await db_session.refresh(item)
    assert item.hidden is True
    assert item.min_auto_units == 12_345
