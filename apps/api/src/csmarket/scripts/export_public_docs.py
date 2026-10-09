"""Export the partner-facing API docs served at docs.csmarket.uz.

Cuts ``/api/v1/public/*`` out of the app's OpenAPI schema with the components it references,
puts the partner guide in ``info.description`` (Scalar shows its headings as the sidebar's
guide) and writes ``openapi.json`` plus ``llms.txt`` (the guide and an endpoint list for
AI agents) and a Postman collection. Run by ``make gen-api``; CI's openapi-drift job diffs the result.

Usage:
    python -m csmarket.scripts.export_public_docs <partner-guide.md> <output dir>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from csmarket.bootstrap import create_app
from csmarket.scripts.postman import postman_collection

_EXPECTED_ARGV = 3  # script name + guide + output dir
_PREFIX = "/api/v1/public"
_SERVER = "https://api.csmarket.uz" + _PREFIX
_SCHEMA_REF = "#/components/schemas/"
_METHODS = ("get", "put", "post", "delete", "patch")
_TAGS = (
    ("/me", "Account", "Your balance, key and limits."),
    ("/catalog", "Catalogue", "Items in stock and their offers."),
    ("/orders", "Orders", "Buying skins and following the orders."),
    ("/webhook", "Webhooks", "Where we send order events."),
)
_RST_CODE = re.compile(r"``([^`]+)``")
# Fake values shown in "Test Request" and the Postman collection (never real ones).
EXAMPLES: dict[str, dict[str, str]] = {
    "ApiOrderIn": {
        "item_id": "4f1c2a9e",
        "offer_id": "Zm9vYmFy",
        "max_price_usd": "14.500",
        "trade_link": "https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE",
        "client_order_id": "shop-1042",
    },
    "WebhookIn": {"url": "https://partner.example/hooks/csmarket"},
}

Json = Any  # Any: arbitrary JSON from FastAPI's schema


def _clean(node: Json) -> Json:
    """Markdown-ify docstring text: RST ````x```` → ```x```, `` -- `` → an em dash."""
    if isinstance(node, str):
        return _RST_CODE.sub(r"`\1`", node).replace(" -- ", " — ")
    if isinstance(node, dict):
        return {key: _clean(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_clean(value) for value in node]
    return node


def _refs(node: Json) -> set[str]:
    """Names of the component schemas ``node`` references directly."""
    if isinstance(node, dict):
        found = set()
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_SCHEMA_REF):
            found.add(ref.removeprefix(_SCHEMA_REF))
        for value in node.values():
            found |= _refs(value)
        return found
    if isinstance(node, list):
        return set().union(*(_refs(value) for value in node))
    return set()


def _closure(paths: Json, schemas: Json) -> dict[str, Json]:
    """The component schemas reachable from ``paths``."""
    todo, seen = _refs(paths), set[str]()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo |= _refs(schemas[name]) - seen
    return {name: schemas[name] for name in sorted(seen)}


def _tag(path: str) -> str:
    return next(tag for prefix, tag, _ in _TAGS if path.startswith(prefix))


def _operation(path: str, op: Json) -> Json:
    """One operation without the ``authorization`` header (the bearer scheme covers it)."""
    op = dict(op)
    params = [p for p in op.get("parameters", []) if p["name"].lower() != "authorization"]
    if params:
        op["parameters"] = params
    else:
        op.pop("parameters", None)
    op["operationId"] = op["operationId"].split("_api_v1_public")[0]
    op["tags"] = [_tag(path)]
    return op


def public_schema(guide: str) -> dict[str, Json]:
    """The public OpenAPI document with ``guide`` as its description."""
    full = create_app().openapi()
    paths = {
        path.removeprefix(_PREFIX) or "/": {
            method: _operation(path.removeprefix(_PREFIX), op)
            for method, op in ops.items()
            if method in _METHODS
        }
        for path, ops in full["paths"].items()
        if path.startswith(_PREFIX + "/")
    }
    schema = {
        "openapi": full["openapi"],
        "info": {"title": "csmarket API", "version": "1.0", "description": guide},
        "servers": [{"url": _SERVER}],
        "security": [{"bearer": []}],
        "tags": [{"name": tag, "description": text} for _, tag, text in _TAGS],
        "paths": paths,
        "components": {
            "schemas": _closure(paths, full["components"]["schemas"]),
            "securitySchemes": {
                "bearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Your API key: `csm_` + 43 characters.",
                }
            },
        },
    }
    cleaned: dict[str, Json] = _clean(schema)
    return _with_examples(_short_names(cleaned))


def _short_names(schema: dict[str, Json]) -> dict[str, Json]:
    """``csmarket__modules__…__MeOut`` → ``MeOut`` (FastAPI's name for a clashing model)."""
    text = json.dumps(schema)
    for name in schema["components"]["schemas"]:
        if "__" in name:
            text = text.replace(f'"{name}"', f'"{name.rsplit("__", 1)[1]}"')
            text = text.replace(
                _SCHEMA_REF + name + '"', _SCHEMA_REF + name.rsplit("__", 1)[1] + '"'
            )
    renamed: dict[str, Json] = json.loads(text)
    return renamed


def _with_examples(schema: dict[str, Json]) -> dict[str, Json]:
    """Put :data:`EXAMPLES` on the request bodies' properties."""
    for model, fields in EXAMPLES.items():
        props = schema["components"]["schemas"][model]["properties"]
        for field, value in fields.items():
            props[field]["examples"] = [value]
    return schema


def llms_txt(schema: dict[str, Json]) -> str:
    """The guide plus one line per endpoint, for AI agents."""
    lines = [f"# {schema['info']['title']}", "", f"Base URL: {_SERVER}", "", "## Endpoints", ""]
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            lines.append(f"- `{method.upper()} {path}` — {op['summary']}")
    lines += ["", "Full schema: https://docs.csmarket.uz/openapi.json", ""]
    return "\n".join(lines) + "\n" + str(schema["info"]["description"])


def main(argv: list[str]) -> int:
    """Write ``openapi.json`` and ``llms.txt`` for the guide ``argv[1]`` into ``argv[2]``."""
    if len(argv) != _EXPECTED_ARGV:
        print(
            "Usage: python -m csmarket.scripts.export_public_docs <guide.md> <output dir>",
            file=sys.stderr,
        )
        return 2

    guide = Path(argv[1]).read_text(encoding="utf-8")
    out = Path(argv[2]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    schema = public_schema(guide)
    (out / "openapi.json").write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "llms.txt").write_text(llms_txt(schema), encoding="utf-8")
    (out / "csmarket.postman_collection.json").write_text(
        json.dumps(postman_collection(schema), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote openapi.json, llms.txt and the Postman collection to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
