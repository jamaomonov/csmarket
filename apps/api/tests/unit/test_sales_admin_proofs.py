"""The receipt's name and type (ADR-0024): what an admin's upload is kept as."""

from __future__ import annotations

import pytest
from csmarket.modules.sales.admin_proofs import clean_name


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
