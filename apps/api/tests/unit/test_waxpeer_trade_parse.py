"""``parse_trade``: one ``check-many-project-id`` entry into a frozen ``WaxpeerTrade``."""

from __future__ import annotations

from datetime import UTC, datetime

import pydantic
import pytest
from csmarket.modules.skins.waxpeer_trades import (
    WaxpeerSeller,
    WaxpeerTrade,
    _classify,
    _new_price_units,
    parse_trade,
)

_SEND_UNTIL = 1790636153


def _raw(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 30717201,
        "project_id": "o-1",
        "status": 4,
        "trade_id": "9393511289",
        "done": False,
        "for_steamid64": "76561190000000002",
        "seller_steam_id": "76561190000000003",
        "reason": None,
        "release_date": None,
        "is_released": False,
        "seller_name": "seller-two",
        "seller_avatar": "https://avatars.example.test/y.jpg",
        "seller_steam_joined": 1730230098,
        "seller_steam_level": 12,
        "price": 6,
        "send_until": str(_SEND_UNTIL),
        "penalties": {},
        "escrow_status": None,
    }
    return {**base, **over}


def test_a_full_entry() -> None:
    trade = parse_trade(_raw(escrow_status="hold"))
    assert trade == WaxpeerTrade(
        id=30717201,
        project_id="o-1",
        status=4,
        trade_id="9393511289",
        done=False,
        reason=None,
        release_date=None,
        is_released=False,
        send_until=datetime.fromtimestamp(_SEND_UNTIL, tz=UTC),
        price_units=6,
        penalties=None,
        escrow_status="hold",
        seller=WaxpeerSeller(
            name="seller-two",
            avatar_url="https://avatars.example.test/y.jpg",
            level=12,
            joined_at=datetime(2024, 10, 29, 19, 28, 18, tzinfo=UTC),
        ),
    )


def test_steam_ids_never_survive_the_parse() -> None:
    trade = parse_trade(_raw())
    text = repr(trade) + trade.model_dump_json()
    assert "76561190000000002" not in text
    assert "76561190000000003" not in text
    assert "for_steamid64" not in trade.model_dump()


@pytest.mark.parametrize("raw", [_SEND_UNTIL, str(_SEND_UNTIL)])
def test_send_until_is_epoch_seconds_string_or_int(raw: object) -> None:
    assert parse_trade(_raw(send_until=raw)).send_until == datetime.fromtimestamp(
        _SEND_UNTIL, tz=UTC
    )


@pytest.mark.parametrize("raw", [None, "", "soon", "1.5e9", True, 0, -5, 10**20, [1]])
def test_bad_epochs_are_none(raw: object) -> None:
    trade = parse_trade(_raw(send_until=raw, seller_steam_joined=raw))
    assert trade.send_until is None
    assert trade.seller.joined_at is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-05T16:00:00.000Z", datetime(2026, 10, 5, 16, tzinfo=UTC)),
        ("2026-10-05T16:00:00+00:00", datetime(2026, 10, 5, 16, tzinfo=UTC)),
        ("2026-10-05T21:00:00+05:00", datetime(2026, 10, 5, 16, tzinfo=UTC)),
    ],
)
def test_release_date_is_iso_8601(raw: str, expected: datetime) -> None:
    parsed = parse_trade(_raw(release_date=raw)).release_date
    assert parsed == expected
    assert parsed is not None
    assert parsed.utcoffset() is not None


@pytest.mark.parametrize("raw", [None, "", "2026-10-05T16:00:00", "yesterday", 1790636153])
def test_naive_or_bad_release_dates_are_none(raw: object) -> None:
    assert parse_trade(_raw(release_date=raw)).release_date is None


@pytest.mark.parametrize("raw", [None, "x", "", [4], 4.5])
def test_unparsable_status_is_minus_one(raw: object) -> None:
    assert parse_trade(_raw(status=raw)).status == -1


def test_numeric_string_fields_are_read() -> None:
    trade = parse_trade(_raw(id="30717201", status="6", price="15", seller_steam_level="3"))
    assert (trade.id, trade.status, trade.price_units, trade.seller.level) == (
        30717201,
        6,
        15,
        3,
    )


def test_bool_is_not_a_number() -> None:
    trade = parse_trade(_raw(status=True, price=True, seller_steam_level=True))
    assert (trade.status, trade.price_units, trade.seller.level) == (-1, 0, None)


@pytest.mark.parametrize("raw", [{}, None, [], "x"])
def test_empty_or_odd_penalties_are_none(raw: object) -> None:
    assert parse_trade(_raw(penalties=raw)).penalties is None


def test_penalties_are_kept_when_present() -> None:
    assert parse_trade(_raw(penalties={"seller": 5})).penalties == {"seller": 5}


def test_seller_mapping_with_blanks() -> None:
    seller = parse_trade(
        _raw(
            seller_name="  ",
            seller_avatar="",
            seller_steam_level=None,
            seller_steam_joined=None,
        )
    ).seller
    assert seller == WaxpeerSeller(name=None, avatar_url=None, level=None, joined_at=None)


def test_seller_name_is_trimmed() -> None:
    assert parse_trade(_raw(seller_name=" bob ")).seller.name == "bob"


def test_a_bare_entry_has_safe_defaults() -> None:
    trade = parse_trade({})
    assert (trade.id, trade.project_id, trade.status, trade.price_units) == (0, "", -1, 0)
    assert (trade.trade_id, trade.reason, trade.escrow_status) == (None, None, None)
    assert (trade.done, trade.is_released) == (False, False)


def test_ids_and_reasons_become_strings() -> None:
    trade = parse_trade(_raw(trade_id=9393511289, reason="Buyer failed to accept", done=1))
    assert (trade.trade_id, trade.reason, trade.done) == (
        "9393511289",
        "Buyer failed to accept",
        True,
    )


def test_models_are_frozen() -> None:
    trade = parse_trade(_raw())
    with pytest.raises(pydantic.ValidationError):
        trade.status = 6  # type: ignore[misc]
    with pytest.raises(pydantic.ValidationError):
        trade.seller.name = "x"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), (" TRUE ", True), ("1", True), ("false", False), ("", False), (0, False)],
)
def test_waxpeer_booleans(raw: object, expected: bool) -> None:
    assert parse_trade(_raw(done=raw, is_released=raw)).done is expected


@pytest.mark.parametrize("body", ["", "not json", "[1]", '{"new_price": null}'])
def test_a_refusal_body_without_a_price(body: str) -> None:
    assert _new_price_units(body) is None


def test_an_unexpected_exception_counts_as_error() -> None:
    assert _classify(RuntimeError("x")) == ("error", None)
