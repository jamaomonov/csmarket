"""The receipt's name and type (ADR-0024): what an admin's upload is kept as."""

from __future__ import annotations

import pytest
from csmarket.modules.sales.admin_proofs import clean_name, sniff


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("чек Humo.png", "чек Humo.png"),
        ("C:\\Users\\admin\\чек.pdf", "чек.pdf"),
        ("../../etc/passwd", "passwd"),
        ("a\x00b\nc.png", "abc.png"),
        ("   ", "receipt.png"),
        (None, "receipt.png"),
        ("x" * 300, "x" * 120),
    ],
    ids=["plain", "windows-path", "unix-path", "control", "blank", "none", "long"],
)
def test_the_name_loses_its_path_and_control_characters(raw: str | None, kept: str) -> None:
    assert clean_name(raw, "image/png") == kept


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
