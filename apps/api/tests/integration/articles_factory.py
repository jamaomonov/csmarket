"""Fixtures for the articles tests: real image headers and ready-made articles."""

from __future__ import annotations

import struct
import zlib


def png(width: int = 640, height: int = 360, salt: bytes = b"") -> bytes:
    """A PNG whose header reads ``width`` × ``height``; ``salt`` makes the bytes unique."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + chunk
        + struct.pack(">I", zlib.crc32(chunk))
        + salt
    )


ADMIN = "/api/v1/admin/articles"


def tr(
    title: str = "Топ бюджетных ножей", *, ready: bool = True, body: str = "Текст."
) -> dict[str, object]:
    """A translation body for the admin API."""
    return {
        "title": title,
        "description": "Описание",
        "cover_alt": "Обложка",
        "body": body,
        "ready": ready,
    }
