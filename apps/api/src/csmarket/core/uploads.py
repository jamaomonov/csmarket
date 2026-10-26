"""Files an admin uploads as the raw request body: payout receipts (ADR-0024), article images.

The type is read from the bytes (:func:`sniff`), never from the name or the client's header; the
body is read in chunks and refused as soon as it passes its cap (:func:`read_capped_body`);
an image's pixel size comes from its header (:func:`image_size`), with no imaging library.
"""

from __future__ import annotations

import struct

from fastapi import Request

from csmarket.core.errors import ValidationError

#: JPEG start-of-frame markers that carry the size (every SOFn except DHT, JPG and DAC).
_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def sniff(data: bytes) -> str | None:
    """The file's type from its first bytes; ``None`` for anything we do not keep."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


async def read_capped_body(request: Request, *, max_bytes: int, too_large_code: str) -> bytes:
    """The request body, refused (422 ``too_large_code``) as soon as it passes ``max_bytes``."""
    message = f"the file is larger than {max_bytes // (1024 * 1024)} MB"
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise ValidationError(message, code=too_large_code)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise ValidationError(message, code=too_large_code)
        chunks.append(chunk)
    return b"".join(chunks)


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return (w, h) if w and h else None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker in _SOF:
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return (w, h) if w and h else None
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        i += 2 + length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    kind, body = data[12:16], data[20:]
    if kind == b"VP8 " and len(body) >= 10 and body[3:6] == b"\x9d\x01\x2a":
        w, h = struct.unpack("<HH", body[6:10])
        return (w & 0x3FFF, h & 0x3FFF)
    if kind == b"VP8L" and len(body) >= 5 and body[0] == 0x2F:
        (bits,) = struct.unpack("<I", body[1:5])
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if kind == b"VP8X" and len(body) >= 10:
        return (int.from_bytes(body[4:7], "little") + 1, int.from_bytes(body[7:10], "little") + 1)
    return None


def image_size(data: bytes, content_type: str) -> tuple[int, int] | None:
    """``(width, height)`` from a JPEG, PNG or WebP header; ``None`` when it cannot be read."""
    if content_type == "image/png":
        return _png_size(data)
    if content_type == "image/jpeg":
        return _jpeg_size(data)
    if content_type == "image/webp":
        return _webp_size(data)
    return None
