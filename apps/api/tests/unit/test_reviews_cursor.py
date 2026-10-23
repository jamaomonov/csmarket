"""The reviews keyset cursor: ``(rank, created_at, id)``, opaque, 422 on a foreign token."""

from datetime import UTC, datetime

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.reviews.cursor import RankCursor, decode_rank_cursor, encode_rank_cursor

AT = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
ID = "6f1c2a1e-6c1b-4b7e-9a51-1f2d3c4b5a69"


def test_round_trip() -> None:
    assert decode_rank_cursor(encode_rank_cursor(1, AT, ID)) == RankCursor(1, AT, ID)


@pytest.mark.parametrize("token", ["x", "", "W10", encode_rank_cursor(0, AT, ID)[:-3]])
def test_a_foreign_token_is_422(token: str) -> None:
    with pytest.raises(ValidationError) as caught:
        decode_rank_cursor(token)
    assert caught.value.extra["code"] == "cursor"
