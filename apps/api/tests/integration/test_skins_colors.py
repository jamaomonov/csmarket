"""Skin colours (spec 2026-10-14-skin-colors): the job, the ``color`` filter and facet, and the
admin's hand-set colours."""

from __future__ import annotations

import io
from collections.abc import Awaitable, Callable

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.skins.color_job import picture_url, refresh_colors
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.naming import slug_for
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
CDN = "https://community.akamai.steamstatic.com/economy/image"
HOST = "community.fastly.steamstatic.com"


def _png(rgb: tuple[int, int, int]) -> bytes:
    img = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
    for x in range(8, 56):
        for y in range(8, 40):
            img.putpixel((x, y), (*rgb, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _row(name: str, image: str | None, **kw: object) -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name=name,
        phase="",
        slug=slug_for(name, ""),
        category="rifles",
        weapon="AK-47",
        skin=name,
        exterior="FT",
        image_url=image,
        search_text=name.lower(),
        min_auto_units=1000,
        count_auto=3,
        active=True,
        cheapest_auto=[{"listing_id": 1, "price_units": 1000}],
        **kw,
    )


async def test_the_job_reads_each_picture_once_for_every_wear(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    db_session.add_all(
        [
            _row("AK-47 | Redline (Field-Tested)", f"{CDN}/red"),
            _row("AK-47 | Redline (Minimal Wear)", f"{CDN}/red"),
            _row("AK-47 | Blue (Field-Tested)", f"{CDN}/blue"),
            _row("AK-47 | Broken (Field-Tested)", f"{CDN}/broken"),
            _row("AK-47 | Down (Field-Tested)", f"{CDN}/down"),
            _row("AK-47 | Set (Field-Tested)", f"{CDN}/set", colors=["pink"], colors_manual=True),
        ]
    )
    await db_session.commit()
    asked: list[str] = []
    bodies = {"red": _png((210, 30, 30)), "blue": _png((40, 90, 230)), "broken": b"not a png"}

    async def fetch(url: str) -> bytes | None:
        asked.append(url)
        return bodies.get(url.split("/")[-2])  # …/<name>/128fx96f; "down" fails

    run = await refresh_colors(factory, fetch=fetch, host=HOST)
    assert (run.pictures, run.read, run.failed) == (4, 3, 1)
    assert all(u.startswith(f"https://{HOST}/") and u.endswith("/128fx96f") for u in asked)
    rows = {r.market_hash_name: r for r in (await db_session.execute(select(SkinItem))).scalars()}
    for r in rows.values():
        await db_session.refresh(r)
    assert rows["AK-47 | Redline (Field-Tested)"].colors == ["red"]
    assert rows["AK-47 | Redline (Minimal Wear)"].colors == ["red"]
    assert rows["AK-47 | Blue (Field-Tested)"].colors == ["blue"]
    # Undecodable: read, no colours, never fetched again. A failed fetch is tried next tick.
    assert rows["AK-47 | Broken (Field-Tested)"].colors == []
    assert rows["AK-47 | Broken (Field-Tested)"].colors_image == f"{CDN}/broken"
    assert rows["AK-47 | Down (Field-Tested)"].colors_image is None
    assert rows["AK-47 | Set (Field-Tested)"].colors == ["pink"]  # manual: untouched
    again = await refresh_colors(factory, fetch=fetch, host=HOST)
    assert again.pictures == 1  # only "down"


def test_picture_url_asks_for_a_small_copy_on_our_host() -> None:
    assert picture_url(f"{CDN}/abc", host=HOST) == f"https://{HOST}/economy/image/abc/128fx96f"


@pytest.fixture
async def coloured(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            _row("AK-47 | Red (Field-Tested)", f"{CDN}/1", colors=["red"]),
            _row("AK-47 | Red Blue (Field-Tested)", f"{CDN}/2", colors=["red", "blue"]),
            _row("AK-47 | Blue (Field-Tested)", f"{CDN}/3", colors=["blue"]),
            _row("AK-47 | Grey (Field-Tested)", f"{CDN}/4", colors=["grey"]),
            _row("AK-47 | New (Field-Tested)", f"{CDN}/5"),
        ]
    )
    await db_session.commit()


async def test_the_catalogue_filters_by_any_named_colour(
    integration_client: AsyncClient, coloured: None
) -> None:
    async def names(query: str) -> set[str]:
        r = await integration_client.get(f"/api/v1/skins/catalog?{query}")
        assert r.status_code == 200, r.text
        return {i["name"] for i in r.json()["items"]}

    assert await names("color=red") == {
        "AK-47 | Red (Field-Tested)",
        "AK-47 | Red Blue (Field-Tested)",
    }
    assert len(await names("color=blue,grey")) == 3
    bad = await integration_client.get("/api/v1/skins/catalog?color=teal")
    assert (bad.status_code, bad.json()["code"]) == (422, "skins_color")
    many = await integration_client.get("/api/v1/skins/catalog?color=red,blue,grey,white")
    assert many.status_code == 422


async def test_facets_count_colours_in_swatch_order(
    integration_client: AsyncClient, coloured: None
) -> None:
    body = (await integration_client.get("/api/v1/skins/facets?category=rifles")).json()
    assert body["colors"] == [
        {"value": "red", "count": 2},
        {"value": "blue", "count": 2},
        {"value": "grey", "count": 1},
    ]


async def test_the_item_page_names_its_colours(
    integration_client: AsyncClient, coloured: None
) -> None:
    body = (await integration_client.get("/api/v1/skins/ak-47-red-blue-field-tested")).json()
    assert body["colors"] == ["red", "blue"]


async def test_an_admin_sets_colours_for_every_wear_and_gives_them_back(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    db_session.add_all(
        [
            _row(
                "AK-47 | Odd (Field-Tested)",
                f"{CDN}/odd",
                colors=["grey"],
                colors_image=f"{CDN}/odd",
            ),
            _row(
                "AK-47 | Odd (Minimal Wear)",
                f"{CDN}/odd",
                colors=["grey"],
                colors_image=f"{CDN}/odd",
            ),
        ]
    )
    await db_session.commit()
    headers = {**(await admin_headers()), "Idempotency-Key": "test-colors-000001"}
    url = "/api/v1/admin/skins/items/ak-47-odd-field-tested/colors"
    r = await integration_client.put(url, json={"colors": ["green", "yellow"]}, headers=headers)
    assert r.status_code == 200, r.text
    assert (r.json()["colors"], r.json()["colors_manual"]) == (["green", "yellow"], True)
    other = (
        await db_session.execute(
            select(SkinItem).where(SkinItem.market_hash_name == "AK-47 | Odd (Minimal Wear)")
        )
    ).scalar_one()
    await db_session.refresh(other)
    assert (other.colors, other.colors_manual) == (["green", "yellow"], True)
    action = await db_session.scalar(
        select(AdminAuditLog.action).where(AdminAuditLog.action == "skins.item.colors")
    )
    assert action == "skins.item.colors"

    headers["Idempotency-Key"] = "test-colors-000002"
    back = await integration_client.put(url, json={"colors": None}, headers=headers)
    assert back.json()["colors_manual"] is False
    await db_session.refresh(other)
    assert other.colors_image is None  # the job reads the picture again

    headers["Idempotency-Key"] = "test-colors-000003"
    bad = await integration_client.put(url, json={"colors": ["teal"]}, headers=headers)
    assert bad.status_code == 422
    three = await integration_client.put(
        url, json={"colors": ["red", "blue", "green"]}, headers=headers
    )
    assert three.status_code == 422
