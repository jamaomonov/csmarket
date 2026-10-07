"""CS2's self-contained inspect links, decoded offline (2026-10-07).

Since 2025 an inspect link can carry the item itself:
``steam://…/+csgo_econ_action_preview%20<hex>``. The hex is ``key ‖ payload ‖ checksum``:
every byte is XOR-ed with ``key`` (0 = plain), ``payload`` is the protobuf
``CEconItemPreviewDataBlock`` and the 4-byte checksum is
``(crc32(key ‖ payload) & 0xffff) ^ (len(payload) × crc32(…))``, big-endian. The older
``S…A…D…`` links name an asset only (reading them needs Steam's game coordinator): ``None``.

Only the fields we show are read — no protobuf dependency (``cs2inspect``, GPL-3.0, was the
cross-check on 2 000 real links).
"""

from __future__ import annotations

import re
import struct
import zlib

from pydantic import BaseModel, ConfigDict

_HEX = re.compile(r"csgo_econ_action_preview(?:%20| )([0-9A-Fa-f]+)$")
#: Field numbers of ``CEconItemPreviewDataBlock`` (and of its ``Sticker``).
_ITEM_ID, _DEFINDEX, _PAINTINDEX, _PAINTWEAR, _PAINTSEED = 2, 3, 4, 7, 8
_STICKERS, _KEYCHAINS = 12, 20
_SLOT, _STICKER_ID, _WEAR = 1, 2, 3
_VARINT, _I64, _LEN, _I32 = 0, 1, 2, 5


class Applied(BaseModel):
    """A sticker or a charm on the item."""

    model_config = ConfigDict(frozen=True)

    slot: int | None
    #: ``def_index`` in the item schema (ByMykel's ``stickers.json`` / ``keychains.json``).
    def_index: int
    wear: float | None = None


class InspectedItem(BaseModel):
    """What a self-contained inspect link says about its item."""

    model_config = ConfigDict(frozen=True)

    asset_id: int | None
    defindex: int | None
    paintindex: int | None
    paintseed: int | None
    float_value: float | None
    stickers: tuple[Applied, ...] = ()
    keychains: tuple[Applied, ...] = ()


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _fields(buf: bytes) -> list[tuple[int, int, int | bytes]]:
    """``(field, wire type, value)`` of one protobuf message, in order."""
    out: list[tuple[int, int, int | bytes]] = []
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        field, wire = key >> 3, key & 7
        value: int | bytes
        if wire == _VARINT:
            value, pos = _varint(buf, pos)
        elif wire == _LEN:
            size, pos = _varint(buf, pos)
            value, pos = buf[pos : pos + size], pos + size
        elif wire == _I32:
            value, pos = buf[pos : pos + 4], pos + 4
        elif wire == _I64:
            value, pos = buf[pos : pos + 8], pos + 8
        else:
            raise ValueError("unknown wire type")
        if pos > len(buf):
            raise ValueError("truncated")
        out.append((field, wire, value))
    return out


def _applied(buf: bytes) -> Applied | None:
    slot = def_index = None
    wear: float | None = None
    for field, wire, value in _fields(buf):
        if field == _SLOT and isinstance(value, int):
            slot = value
        elif field == _STICKER_ID and isinstance(value, int):
            def_index = value
        elif field == _WEAR and wire == _I32 and isinstance(value, bytes):
            wear = struct.unpack("<f", value)[0]
    return None if not def_index else Applied(slot=slot, def_index=def_index, wear=wear)


def _checksum(key: int, payload: bytes) -> bytes:
    crc = zlib.crc32(bytes([key]) + payload)
    return struct.pack(">I", ((crc & 0xFFFF) ^ (len(payload) * crc)) & 0xFFFFFFFF)


def _item(payload: bytes) -> InspectedItem:
    ints: dict[int, int] = {}
    stickers: list[Applied] = []
    keychains: list[Applied] = []
    for field, _, value in _fields(payload):
        if isinstance(value, int):
            ints[field] = value
        elif field in (_STICKERS, _KEYCHAINS) and (applied := _applied(value)) is not None:
            (stickers if field == _STICKERS else keychains).append(applied)
    wear = ints.get(_PAINTWEAR)
    return InspectedItem(
        asset_id=ints.get(_ITEM_ID),
        defindex=ints.get(_DEFINDEX),
        paintindex=ints.get(_PAINTINDEX),
        paintseed=ints.get(_PAINTSEED),
        float_value=None if wear is None else struct.unpack("<f", struct.pack("<I", wear))[0],
        stickers=tuple(stickers),
        keychains=tuple(keychains),
    )


def decode_inspect(url: str | None) -> InspectedItem | None:
    """The item a self-contained inspect link carries; ``None`` for any other link, or for one
    that is malformed or whose checksum does not add up."""
    match = _HEX.search(url or "")
    if match is None or len(match.group(1)) % 2:
        return None
    raw = bytes.fromhex(match.group(1))
    if len(raw) < 6:
        return None
    key = raw[0]
    if key:
        raw = bytes(b ^ key for b in raw)
    payload, checksum = raw[1:-4], raw[-4:]
    if _checksum(key, payload) != checksum:
        return None
    try:
        return _item(payload)
    except (ValueError, IndexError, struct.error):
        return None


__all__ = ["Applied", "InspectedItem", "decode_inspect"]
