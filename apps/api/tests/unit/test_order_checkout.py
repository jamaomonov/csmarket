"""Checkout's OpenAPI: the replayed 200 is documented."""

from __future__ import annotations


def test_the_replay_200_is_documented() -> None:
    from csmarket.bootstrap import create_app

    responses = create_app().openapi()["paths"]["/api/v1/orders"]["post"]["responses"]
    for status in ("200", "201"):
        schema = responses[status]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/OrderOut"}
    assert responses["200"]["description"] == "replayed key"
