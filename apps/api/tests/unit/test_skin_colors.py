"""A skin's colours from its picture (spec 2026-10-14-skin-colors)."""

from __future__ import annotations

from collections import Counter

import pytest
from csmarket.modules.skins.colors import SKIN_COLORS, SkinColor, classify, colors_of, pick
from PIL import Image


@pytest.mark.parametrize(
    ("rgb", "group"),
    [
        ((214, 40, 40), "red"),
        ((110, 10, 20), "red"),  # maroon
        ((240, 130, 40), "orange"),
        ((245, 215, 60), "yellow"),
        ((212, 175, 55), "yellow"),  # gold
        ((80, 160, 50), "green"),
        ((180, 220, 60), "green"),  # lime
        ((40, 100, 230), "blue"),
        ((110, 200, 240), "blue"),  # sky
        ((20, 160, 160), "blue"),  # teal goes to blue (owner ruling)
        ((120, 30, 140), "purple"),
        ((225, 80, 210), "pink"),
        ((240, 160, 170), "pink"),  # washed red
        ((110, 70, 40), "brown"),
        ((205, 180, 145), "beige"),
        ((10, 10, 12), "black"),
        ((250, 250, 248), "white"),
        ((140, 140, 140), "grey"),
    ],
)
def test_classify(rgb: tuple[int, int, int], group: SkinColor) -> None:
    assert classify(*rgb) == group


def test_metal_and_shadows_stop_counting_on_a_coloured_skin() -> None:
    # AK-47 | Redline: mostly black metal, a red stripe.
    assert pick(Counter({"black": 45, "grey": 25, "red": 30})) == ["red"]


def test_white_counts_on_colour_when_it_is_large() -> None:
    assert pick(Counter({"white": 40, "orange": 35, "grey": 25})) == ["white", "orange"]
    assert pick(Counter({"white": 10, "orange": 60, "grey": 30})) == ["orange"]


def test_a_colourless_skin_gets_its_neutrals() -> None:
    assert pick(Counter({"grey": 70, "black": 25, "blue": 5})) == ["grey", "black"]


def test_a_weak_second_colour_is_dropped() -> None:
    assert pick(Counter({"blue": 80, "pink": 15, "grey": 5})) == ["blue"]
    assert pick(Counter({"blue": 50, "pink": 30, "grey": 20})) == ["blue", "pink"]


def test_an_empty_picture_has_no_colour() -> None:
    assert pick(Counter()) == []


def test_colors_of_ignores_the_transparent_background() -> None:
    img = Image.new("RGBA", (200, 100), (255, 255, 255, 0))  # white, but transparent
    for x in range(40, 160):
        for y in range(30, 70):
            img.putpixel((x, y), (200, 30, 30, 255))
    assert colors_of(img) == ["red"]


def test_every_group_has_a_key() -> None:
    assert len(SKIN_COLORS) == 12
    assert len(set(SKIN_COLORS)) == 12
