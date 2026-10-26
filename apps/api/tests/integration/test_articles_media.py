"""Article images: an admin uploads, anyone reads them back, immutable (spec 2026-10-26)."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.articles.models import ArticleMedia
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.articles_factory import png

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
UPLOAD = "/api/v1/admin/articles/media"


def _key(n: int) -> dict[str, str]:
    return {"Idempotency-Key": f"test-article-media-{n:06d}", "Content-Type": "image/png"}


async def test_admin_uploads_an_image_and_anyone_reads_it(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    data = png(1280, 720)
    r = await integration_client.post(
        UPLOAD, content=data, headers={**await admin_headers(), **_key(1)}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    digest = hashlib.sha256(data).hexdigest()
    assert body == {
        "hash": digest,
        "url": f"/media/{digest}.png",
        "width": 1280,
        "height": 720,
        "content_type": "image/png",
    }
    got = await integration_client.get(f"/api/v1/media/{digest}.png")
    assert got.status_code == 200
    assert got.content == data
    assert got.headers["content-type"] == "image/png"
    assert got.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert got.headers["x-content-type-options"] == "nosniff"
    actions = (await db_session.scalars(select(AdminAuditLog.action))).all()
    assert "articles.media.add" in actions


async def test_same_bytes_twice_is_one_media(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    data = png(10, 10, b"same")
    first = await integration_client.post(UPLOAD, content=data, headers={**h, **_key(2)})
    second = await integration_client.post(UPLOAD, content=data, headers={**h, **_key(3)})
    assert first.json() == second.json()
    count = await db_session.scalar(select(func.count()).select_from(ArticleMedia))
    assert count == 1


async def test_a_replay_answers_the_same_and_a_different_body_conflicts(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    first = await integration_client.post(UPLOAD, content=png(salt=b"a"), headers={**h, **_key(4)})
    again = await integration_client.post(UPLOAD, content=png(salt=b"a"), headers={**h, **_key(4)})
    other = await integration_client.post(UPLOAD, content=png(salt=b"b"), headers={**h, **_key(4)})
    assert again.json() == first.json()
    assert other.status_code == 409


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "media_empty"),
        (b"%PDF-1.7\n" + b"\x00" * 64, "media_type"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "media_type"),
        (b"<html><script>alert(1)</script></html>", "media_type"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "media_type"),
        (png() + b"\x00" * (5 * 1024 * 1024), "media_too_large"),
    ],
    ids=["empty", "pdf", "svg", "html", "png-no-header", "large"],
)
async def test_what_is_not_a_small_image_is_refused(
    integration_client: AsyncClient, admin_headers: Headers, data: bytes, code: str
) -> None:
    r = await integration_client.post(
        UPLOAD, content=data, headers={**await admin_headers(), **_key(5)}
    )
    assert r.status_code == 422
    assert r.json()["code"] == code


async def test_wrong_extension_or_unknown_hash_is_404(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    r = await integration_client.post(
        UPLOAD, content=png(salt=b"x"), headers={**await admin_headers(), **_key(6)}
    )
    digest = r.json()["hash"]
    assert (await integration_client.get(f"/api/v1/media/{digest}.jpg")).status_code == 404
    assert (await integration_client.get(f"/api/v1/media/{'0' * 64}.png")).status_code == 404
    assert (await integration_client.get("/api/v1/media/not-a-hash.png")).status_code == 404


async def test_a_customer_cannot_upload(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    r = await integration_client.post(
        UPLOAD, content=png(), headers={**await customer_headers(), **_key(7)}
    )
    assert r.status_code == 403
