"""``make gen-api`` writes a deterministic schema CI can diff."""

from __future__ import annotations

import json
from pathlib import Path

from csmarket.scripts.export_openapi import main


def test_writes_sorted_schema(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "openapi.json"
    assert main(["export_openapi", str(out)]) == 0
    schema = json.loads(out.read_text())
    assert schema["info"]["title"] == "csmarket API"
    assert "/healthz" in schema["paths"]
    assert "/readyz" in schema["paths"]
    assert out.read_text() == json.dumps(schema, indent=2, sort_keys=True) + "\n"


def test_usage_error_without_a_path() -> None:
    assert main(["export_openapi"]) == 2
