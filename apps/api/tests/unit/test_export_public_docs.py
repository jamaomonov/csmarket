"""``make gen-api`` writes the partner-facing schema and ``llms.txt`` for docs.csmarket.uz."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from csmarket.scripts.export_public_docs import main, public_schema

_GUIDE = "# Introduction\n\nHello ``partner``.\n"


def _walk_strings(node: Any) -> list[str]:  # Any: arbitrary JSON
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _walk_strings(value)]
    if isinstance(node, list):
        return [s for value in node for s in _walk_strings(value)]
    return []


def _refs(node: Any) -> set[str]:  # Any: arbitrary JSON
    if isinstance(node, dict):
        found = {node["$ref"]} if isinstance(node.get("$ref"), str) else set()
        return found.union(*(_refs(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(_refs(v) for v in node))
    return set()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:  # Any: arbitrary JSON
    return public_schema(_GUIDE)


def test_only_public_paths_relative_to_the_base(schema: dict[str, Any]) -> None:
    assert schema["paths"]
    assert all(not p.startswith("/api/") for p in schema["paths"])
    assert "/orders" in schema["paths"]
    assert "/healthz" not in schema["paths"]
    assert schema["servers"] == [{"url": "https://api.csmarket.uz/api/v1/public"}]


def test_every_ref_resolves_and_nothing_extra(schema: dict[str, Any]) -> None:
    refs = _refs(schema)
    names = {r.rsplit("/", 1)[1] for r in refs}
    assert names == set(schema["components"]["schemas"])
    assert "AdminOrderFull" not in schema["components"]["schemas"]


def test_bearer_replaces_the_authorization_parameter(schema: dict[str, Any]) -> None:
    assert schema["components"]["securitySchemes"]["bearer"]["scheme"] == "bearer"
    assert schema["security"] == [{"bearer": []}]
    for ops in schema["paths"].values():
        for op in ops.values():
            names = {p["name"].lower() for p in op.get("parameters", [])}
            assert "authorization" not in names
            assert op["tags"]


def test_guide_and_markdown_cleanup(schema: dict[str, Any]) -> None:
    assert schema["info"]["description"] == "# Introduction\n\nHello `partner`.\n"
    assert schema["info"]["version"] == "1.0"
    assert not [s for s in _walk_strings(schema) if "``" in s]


def test_main_writes_both_files(tmp_path: Path) -> None:
    guide = tmp_path / "guide.md"
    guide.write_text(_GUIDE, encoding="utf-8")
    out = tmp_path / "site"
    assert main(["export_public_docs", str(guide), str(out)]) == 0
    text = (out / "openapi.json").read_text()
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    llms = (out / "llms.txt").read_text()
    assert llms.startswith("# csmarket API")
    assert "Hello `partner`." in llms
    assert "- `POST /orders` — Buy one skin from the USD wallet" in llms


def test_usage_error_without_paths() -> None:
    assert main(["export_public_docs"]) == 2
