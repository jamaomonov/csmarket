"""``skins.inspect.decode_inspect``: CS2's self-contained inspect links, decoded offline.

The three links are real Skinslink listings of AK-47 | Redline (Field-Tested) (2026-10-07);
the expected values were cross-checked against the ``cs2inspect`` library on 2 000 links.
"""

from __future__ import annotations

import pytest
from csmarket.modules.skins.inspect import decode_inspect

#: A masked link (the first byte is the XOR key).
MASKED = (
    "steam://run/730//+csgo_econ_action_preview%20"
    "1303E5CC9FB9DB120B143389113B1623172BA1F6FEE61053E81771161B1303A73A71161B1203A73A71161B11"
    "03A73A71161B1003A73A7B909393931F631B4996D743"
)
#: Unmasked (key 0).
PLAIN = (
    "steam://run/730/en/+csgo_econ_action_preview%20"
    "0010B8E999E8601807209A022805300438FCB195F40340F606620408001033620408011"
    "03E62040802103A62040803104068037008F05C27A1"
)


def test_a_masked_link_gives_the_item_and_its_stickers() -> None:
    item = decode_inspect(MASKED)
    assert item is not None
    assert (item.asset_id, item.defindex, item.paintindex, item.paintseed) == (
        53775380470,
        7,
        282,
        635,
    )
    assert item.float_value == pytest.approx(0.36610943)
    assert [(s.slot, s.def_index) for s in item.stickers] == [
        (0, 5300),
        (1, 5300),
        (2, 5300),
        (3, 5300),
    ]
    assert item.keychains == ()


def test_an_unmasked_link_decodes_the_same_way() -> None:
    item = decode_inspect(PLAIN)
    assert item is not None
    assert item.asset_id == 25988330680
    assert [s.def_index for s in item.stickers] == [51, 62, 58, 64]


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20S1A2D3",
        "https://example.com/preview%20ABCDEF",
        "steam://run/730//+csgo_econ_action_preview%20ZZZZ",
        "steam://run/730//+csgo_econ_action_preview%20" + "00" * 3,
        MASKED[:-12],  # cut short: the checksum no longer adds up
    ],
)
def test_anything_else_is_none(url: str | None) -> None:
    assert decode_inspect(url) is None
