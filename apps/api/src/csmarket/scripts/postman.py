"""A Postman v2.1 collection built from the public OpenAPI document.

Used by :mod:`csmarket.scripts.export_public_docs`. One folder per tag, the key as a
collection-level bearer token in ``{{token}}``, the base URL in ``{{baseUrl}}``, and request
bodies filled with the schema's fake ``examples``.
"""

from __future__ import annotations

import json
import re
from typing import Any

Json = Any  # Any: arbitrary JSON from the OpenAPI document

_SCHEMA_REF = "#/components/schemas/"
_PATH_PARAM = re.compile(r"\{([^}]+)\}")
_FAKE_TOKEN = "csm_EXAMPLEtokenNotReal"  # noqa: S105 -- a placeholder, not a key
_POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def _body(op: Json, schemas: Json) -> Json | None:
    """A raw JSON body from the request schema's examples, or ``None`` without a body."""
    content = op.get("requestBody", {}).get("content", {}).get("application/json")
    if content is None:
        return None
    model = schemas[content["schema"]["$ref"].removeprefix(_SCHEMA_REF)]
    example = {
        name: prop["examples"][0]
        for name, prop in model["properties"].items()
        if prop.get("examples")
    }
    return {
        "mode": "raw",
        "raw": json.dumps(example, indent=2),
        "options": {"raw": {"language": "json"}},
    }


def _headers(op: Json) -> list[dict[str, str]]:
    headers = [
        {"key": p["name"], "value": "{{$guid}}"}
        for p in op.get("parameters", [])
        if p["in"] == "header" and p["name"].lower() == "idempotency-key"
    ]
    if "requestBody" in op:
        headers.append({"key": "Content-Type", "value": "application/json"})
    return headers


def _url(path: str, op: Json) -> Json:
    postman_path = _PATH_PARAM.sub(r":\1", path)
    url: Json = {
        "raw": "{{baseUrl}}" + postman_path,
        "host": ["{{baseUrl}}"],
        "path": [part for part in postman_path.split("/") if part],
    }
    params = op.get("parameters", [])
    query = [
        {"key": p["name"], "value": "", "disabled": True, "description": p.get("description", "")}
        for p in params
        if p["in"] == "query"
    ]
    if query:
        url["query"] = query
    variables = [{"key": p["name"], "value": ""} for p in params if p["in"] == "path"]
    if variables:
        url["variable"] = variables
    return url


def _request(path: str, method: str, op: Json, schemas: Json) -> Json:
    request: Json = {
        "method": method.upper(),
        "header": _headers(op),
        "url": _url(path, op),
        "description": op.get("description", ""),
    }
    body = _body(op, schemas)
    if body is not None:
        request["body"] = body
    return {"name": op["summary"], "request": request}


def postman_collection(schema: dict[str, Json]) -> dict[str, Json]:
    """The collection for ``schema`` (the output of ``public_schema``)."""
    schemas = schema["components"]["schemas"]
    folders: dict[str, list[Json]] = {tag["name"]: [] for tag in schema["tags"]}
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            folders[op["tags"][0]].append(_request(path, method, op, schemas))
    return {
        "info": {
            "name": schema["info"]["title"],
            "description": "Set `token` to your API key. Guide: https://docs.csmarket.uz",
            "schema": _POSTMAN_SCHEMA,
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}],
        },
        "variable": [
            {"key": "baseUrl", "value": schema["servers"][0]["url"]},
            {"key": "token", "value": _FAKE_TOKEN},
        ],
        "item": [
            {"name": tag["name"], "description": tag["description"], "item": folders[tag["name"]]}
            for tag in schema["tags"]
        ],
    }
