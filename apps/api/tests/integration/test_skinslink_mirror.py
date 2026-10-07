"""The mirror of Skinslink's stock: full load, events, reset, staleness, mapping."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from csmarket.core.config import get_settings
from csmarket.modules.skinslink.api import (
    AvailablePage,
    CatalogueEvent,
    CatalogueItem,
    EventsPage,
)
from csmarket.modules.skinslink.mirror import mirror_fresh, split_phase, sync_mirror, to_units
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _item(id_: str, name: str, price: str, phase: str | None = None) -> CatalogueItem:
    return CatalogueItem(
        id=id_,
        name=name,
        price_usd=Decimal(price),
        image_url="https://i.test/x.png",
        phase=phase,
        float_value=0.2,
        paint_seed=1,
        inspect_url=None,
    )


class ScriptedClient:
    """Answers in order; records what it was asked."""

    def __init__(self, *answers: AvailablePage | EventsPage) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, str | None]] = []

    async def available_batches(
        self,
        on_batch: Callable[[list[CatalogueItem]], Awaitable[None]],
        *,
        game: str = "csgo",
        batch_size: int = 1000,
    ) -> str:
        """Streams the scripted page one item per batch (as a long list arrives)."""
        self.asked.append(("available", None))
        answer = self.answers.pop(0)
        assert isinstance(answer, AvailablePage)
        for item in answer.items:
            await on_batch([item])
        return answer.last_update_at

    async def events(self, since: str, *, game: str = "csgo", limit: int = 10000) -> EventsPage:
        self.asked.append(("events", since))
        answer = self.answers.pop(0)
        assert isinstance(answer, EventsPage)
        return answer


def _factory(engine: AsyncEngine) -> Callable[[], AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False)


async def _rows(db: AsyncSession) -> dict[str, SkinslinkItem]:
    found = await db.scalars(select(SkinslinkItem).execution_options(populate_existing=True))
    return {r.id: r for r in found.all()}


async def test_first_tick_loads_everything_and_maps_known_names(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    client = ScriptedClient(
        AvailablePage(
            items=[
                _item("1", item.market_hash_name, "12.45"),
                _item("2", "Nope | Nothing (Field-Tested)", "1.00"),
            ],
            last_update_at="2026-10-06T11:59:00Z",
        )
    )
    result = await sync_mirror(_factory(db_engine), client, now=NOW)
    assert (result.mode, result.upserts) == ("full", 2)
    rows = await _rows(db_session)
    assert rows["1"].skin_item_id == item.id
    assert rows["1"].price_units == 12450
    assert rows["2"].skin_item_id is None
    state = await db_session.get(SkinslinkState, 1, populate_existing=True)
    assert state is not None
    assert state.cursor == "2026-10-06T11:59:00Z"
    assert state.mirror_synced_at == NOW


async def test_events_apply_upsert_and_remove_and_follow_more(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    client = ScriptedClient(
        AvailablePage(items=[_item("1", name, "10.00")], last_update_at="c0"),
        EventsPage(
            since="c0",
            next="c1",
            more=True,
            reset=False,
            events=[CatalogueEvent(type="upsert", at="x", id="1", item=_item("1", name, "9.00"))],
        ),
        EventsPage(
            since="c1",
            next="c2",
            more=False,
            reset=False,
            events=[
                CatalogueEvent(type="remove", at="x", id="1", item=None),
                CatalogueEvent(type="upsert", at="x", id="3", item=_item("3", name, "8.00")),
            ],
        ),
    )
    await sync_mirror(_factory(db_engine), client, now=NOW)
    result = await sync_mirror(_factory(db_engine), client, now=NOW + timedelta(seconds=15))
    assert (result.mode, result.pages, result.upserts, result.removes) == ("events", 2, 2, 1)
    assert client.asked[1:] == [("events", "c0"), ("events", "c1")]
    assert sorted(await _rows(db_session)) == ["3"]
    state = await db_session.get(SkinslinkState, 1, populate_existing=True)
    assert state is not None
    assert state.cursor == "c2"


async def test_reapplying_an_event_is_safe(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    again = EventsPage(
        since="c0",
        next="c1",
        more=False,
        reset=False,
        events=[
            CatalogueEvent(type="upsert", at="x", id="1", item=_item("1", name, "9.00")),
            CatalogueEvent(type="remove", at="x", id="404", item=None),
        ],
    )
    client = ScriptedClient(AvailablePage(items=[], last_update_at="c0"), again, again)
    for _ in range(3):
        await sync_mirror(_factory(db_engine), client, now=NOW)
    rows = await _rows(db_session)
    assert list(rows) == ["1"]
    assert rows["1"].price_units == 9000


async def test_reset_reloads_everything(db_session: AsyncSession, db_engine: AsyncEngine) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    client = ScriptedClient(
        AvailablePage(items=[_item("1", name, "10.00")], last_update_at="c0"),
        EventsPage(since="c0", next="c0", more=False, reset=True, events=[]),
        AvailablePage(items=[_item("9", name, "7.00")], last_update_at="c9"),
    )
    await sync_mirror(_factory(db_engine), client, now=NOW)
    result = await sync_mirror(_factory(db_engine), client, now=NOW)
    assert result.mode == "reset"
    assert list(await _rows(db_session)) == ["9"]


async def test_unmapped_items_are_kept_but_never_offered(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    client = ScriptedClient(
        AvailablePage(
            items=[_item("1", "★ Karambit | Doppler (Factory New)", "900.00", phase=None)],
            last_update_at="c0",
        )
    )
    await sync_mirror(_factory(db_engine), client, now=NOW)
    row = (await _rows(db_session))["1"]
    assert row.skin_item_id is None
    assert row.phase == ""


async def test_a_phase_maps_to_the_phased_item(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    item.phase = "Phase 2"
    await db_session.commit()
    client = ScriptedClient(
        AvailablePage(
            items=[
                _item("1", item.market_hash_name, "900.00", phase="Phase 2"),
                _item("2", item.market_hash_name, "900.00", phase="Phase 3"),
            ],
            last_update_at="c0",
        )
    )
    await sync_mirror(_factory(db_engine), client, now=NOW)
    rows = await _rows(db_session)
    assert rows["1"].skin_item_id == item.id
    assert rows["2"].skin_item_id is None


async def test_mirror_fresh_follows_the_stale_minutes(db_session: AsyncSession) -> None:
    settings = get_settings()
    assert await mirror_fresh(db_session, settings=settings, now=NOW) is False  # never synced
    db_session.add(SkinslinkState(id=1, mirror_synced_at=NOW - timedelta(minutes=9)))
    await db_session.commit()
    assert await mirror_fresh(db_session, settings=settings, now=NOW) is True
    later = NOW + timedelta(minutes=2)
    assert await mirror_fresh(db_session, settings=settings, now=later) is False


def test_units_and_phase() -> None:
    assert to_units(Decimal("12.45")) == 12450
    assert to_units(Decimal("0.0005")) == 1
    karambit = "★ Karambit | Doppler (Factory New)"
    assert split_phase(karambit, "Phase 2") == (karambit, "Phase 2")
    assert split_phase("AK-47 | Redline (Field-Tested)", None) == (
        "AK-47 | Redline (Field-Tested)",
        "",
    )


async def test_one_page_with_an_id_twice_applies_its_events_in_order(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    page = EventsPage(
        since="c0",
        next="c1",
        more=False,
        reset=False,
        events=[
            CatalogueEvent(type="upsert", at="x", id="1", item=_item("1", name, "9.00")),
            CatalogueEvent(type="upsert", at="x", id="1", item=_item("1", name, "8.50")),
            CatalogueEvent(type="upsert", at="x", id="2", item=_item("2", name, "7.00")),
            CatalogueEvent(type="remove", at="x", id="2", item=None),
            CatalogueEvent(type="upsert", at="x", id="2", item=_item("2", name, "7.25")),
            CatalogueEvent(type="upsert", at="x", id="3", item=_item("3", name, "6.00")),
            CatalogueEvent(type="remove", at="x", id="3", item=None),
        ],
    )
    client = ScriptedClient(AvailablePage(items=[], last_update_at="c0"), page)
    for _ in range(2):
        await sync_mirror(_factory(db_engine), client, now=NOW)
    rows = await _rows(db_session)
    assert {k: v.price_units for k, v in rows.items()} == {"1": 8500, "2": 7250}
    state = await db_session.get(SkinslinkState, 1, populate_existing=True)
    assert state is not None
    assert state.cursor == "c1"


async def test_a_full_load_streamed_in_batches_keeps_the_last_copy_of_an_id(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    page = AvailablePage(
        items=[_item("1", name, "9.00"), _item("2", name, "7.00"), _item("1", name, "8.50")],
        last_update_at="c0",
    )
    await sync_mirror(_factory(db_engine), ScriptedClient(page), now=NOW)
    rows = await _rows(db_session)
    assert {k: v.price_units for k, v in rows.items()} == {"1": 8500, "2": 7000}


async def test_offers_held_in_stock_keep_their_hex_id(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """Skinslink names offers held in stock (no particular asset) by a long hex id; they
    are offers like any other, bought by that id."""
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    stock = "b02411dfd3c832a218902fba32064b26eb22de0719ed1937f128a57276f1a417f7d77e" * 3
    page = AvailablePage(
        items=[_item("1", name, "9.00"), _item(stock, name, "1.05"), _item("Bad-Id", name, "1")],
        last_update_at="c0",
    )
    events = EventsPage(
        since="c0",
        next="c1",
        more=False,
        reset=False,
        events=[CatalogueEvent(type="upsert", at="x", id=stock, item=_item(stock, name, "1.10"))],
    )
    client = ScriptedClient(page, events)
    for _ in range(2):
        await sync_mirror(_factory(db_engine), client, now=NOW)
    rows = await _rows(db_session)
    assert sorted(rows) == sorted(["1", stock])
    assert rows[stock].price_units == 1100
