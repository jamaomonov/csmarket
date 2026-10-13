"""A skin's own colours, read from its Steam picture (spec 2026-10-14-skin-colors) — pure, no I/O.

ByMykel has no palette (``rarity_color`` is the grade's, not the skin's), so the picture is
read: shrunk, its transparent background dropped, every pixel put in one of twelve broad
groups by hue, saturation and brightness (blue holds sky, sapphire, cyan and teal; yellow
holds gold; red holds maroon…). The weapon's own metal is grey and its shadows black: once a
skin has real colour, grey and black stop counting and white needs a large share, so
AK-47 | Redline reads red, not grey, and AWP | Asiimov reads white and orange. A skin with no
real colour gets its largest neutral. At most two colours, each holding a fair share.
"""

from __future__ import annotations

import colorsys
from collections import Counter
from collections.abc import Iterable
from typing import Literal, get_args

from PIL import Image

SkinColor = Literal[
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "purple",
    "pink",
    "brown",
    "beige",
    "black",
    "white",
    "grey",
]
SKIN_COLORS: tuple[SkinColor, ...] = get_args(SkinColor)
NEUTRALS: frozenset[SkinColor] = frozenset({"black", "white", "grey"})

#: The picture is read at this width at most: enough for colours, cheap to scan.
_SIZE = 96
#: A pixel at least this opaque is part of the item.
_OPAQUE = 128
#: With at least this share of coloured pixels, grey and black stop counting.
_COLOURED_SHARE = 0.12
#: White still counts on a coloured skin when it holds at least this share of the item.
_WHITE_ON_COLOUR = 0.25
#: A colour is named when it holds at least this share of the counted pixels…
_MIN_SHARE = 0.18
#: …and a second one only when it holds at least this share of the first's.
_SECOND_OF_FIRST = 0.35
MAX_COLORS = 2


def classify(r: int, g: int, b: int) -> SkinColor:
    """The group of one pixel (0–255 channels)."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    deg = h * 360
    if v < 0.16:
        return "black"
    if s < 0.14 or (s < 0.22 and v < 0.35):
        if v > 0.82:
            return "white"
        return "black" if v < 0.22 else "grey"
    warm = 15 <= deg < 50
    if warm and s < 0.42 and v > 0.55:
        return "beige"
    if warm and v < 0.55:
        return "brown"
    return _hue(deg, s, v)


#: Hue bands (upper bound in degrees, exclusive) between red and magenta.
_BANDS: tuple[tuple[float, SkinColor], ...] = (
    (40, "orange"),
    (68, "yellow"),
    (165, "green"),
    (255, "blue"),
    (300, "purple"),
)


def _hue(deg: float, s: float, v: float) -> SkinColor:
    """A saturated pixel's group by hue (degrees)."""
    if deg < 12 or deg >= 340:
        # A light, washed red reads pink.
        return "pink" if s < 0.45 and v > 0.75 else "red"
    if deg >= 300:
        # Magenta: dark reads purple, bright reads pink.
        return "purple" if deg < 320 and v < 0.6 else "pink"
    return next(colour for top, colour in _BANDS if deg < top)


def histogram(pixels: Iterable[tuple[int, int, int, int]]) -> Counter[SkinColor]:
    """Opaque pixels per group."""
    counts: Counter[SkinColor] = Counter()
    for r, g, b, a in pixels:
        if a >= _OPAQUE:
            counts[classify(r, g, b)] += 1
    return counts


def pick(counts: Counter[SkinColor]) -> list[SkinColor]:
    """The skin's one or two colours from its histogram; ``[]`` for an empty picture."""
    total = sum(counts.values())
    if total == 0:
        return []
    coloured = sum(c for k, c in counts.items() if k not in NEUTRALS)
    if coloured / total >= _COLOURED_SHARE:
        counted = {k: c for k, c in counts.items() if k not in NEUTRALS}
        if counts["white"] / total >= _WHITE_ON_COLOUR:
            counted["white"] = counts["white"]
    else:
        counted = {k: c for k, c in counts.items() if k in NEUTRALS}
    base = sum(counted.values())
    ranked = sorted(counted.items(), key=lambda kc: (-kc[1], SKIN_COLORS.index(kc[0])))
    first_colour, first = ranked[0]
    chosen = [first_colour]
    for colour, count in ranked[1:MAX_COLORS]:
        if count / base >= _MIN_SHARE and count / first >= _SECOND_OF_FIRST:
            chosen.append(colour)
    return chosen


def colors_of(image: Image.Image) -> list[SkinColor]:
    """The colours of a skin picture (any mode; transparency is the background)."""
    img = image.convert("RGBA")
    img.thumbnail((_SIZE, _SIZE))
    # RGBA guarantees 4-tuples of ints; Pillow types the pixels loosely.
    pixels: Iterable[tuple[int, int, int, int]] = img.get_flattened_data()  # type: ignore[assignment]
    return pick(histogram(pixels))


__all__ = [
    "MAX_COLORS",
    "NEUTRALS",
    "SKIN_COLORS",
    "SkinColor",
    "classify",
    "colors_of",
    "histogram",
    "pick",
]
