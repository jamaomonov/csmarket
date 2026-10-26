"""Upload helpers shared by payout receipts and article images (``core/uploads.py``)."""

from __future__ import annotations

import struct
import zlib

import pytest
from csmarket.core.uploads import image_size, sniff


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"\xff\xd8\xff\xdb", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"RIFF\x10\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"%PDF-1.4", "application/pdf"),
        (b"RIFF\x10\x00\x00\x00WAVEfmt ", None),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", None),
        (b"GIF89a", None),
    ],
    ids=["jpeg", "png", "webp", "pdf", "wav", "svg", "gif"],
)
def test_the_type_is_read_from_the_first_bytes(data: bytes, kind: str | None) -> None:
    assert sniff(data) == kind


def _png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + chunk
        + struct.pack(">I", zlib.crc32(chunk))
    )


def _jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc2" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def _riff(chunk: bytes) -> bytes:
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk


def test_png_size() -> None:
    assert image_size(_png(640, 360), "image/png") == (640, 360)


def test_jpeg_size_from_its_frame_header() -> None:
    assert image_size(_jpeg(1280, 720), "image/jpeg") == (1280, 720)


def test_webp_lossy_size() -> None:
    body = b"\x00\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", 800, 450)
    assert image_size(_riff(b"VP8 " + struct.pack("<I", len(body)) + body), "image/webp") == (
        800,
        450,
    )


def test_webp_lossless_size() -> None:
    bits = (300 - 1) | ((200 - 1) << 14)
    body = b"\x2f" + struct.pack("<I", bits)
    assert image_size(_riff(b"VP8L" + struct.pack("<I", len(body)) + body), "image/webp") == (
        300,
        200,
    )


def test_webp_extended_size() -> None:
    body = b"\x00\x00\x00\x00" + (1920 - 1).to_bytes(3, "little") + (1080 - 1).to_bytes(3, "little")
    assert image_size(_riff(b"VP8X" + struct.pack("<I", len(body)) + body), "image/webp") == (
        1920,
        1080,
    )


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff\xd9", "image/jpeg"),
        (b"RIFF\x10\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"garbage", "image/png"),
    ],
    ids=["png-cut", "jpeg-no-frame", "webp-cut", "garbage"],
)
def test_unreadable_headers_have_no_size(data: bytes, kind: str) -> None:
    assert image_size(data, kind) is None
