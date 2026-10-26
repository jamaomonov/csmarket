"""«Подтверждение оплаты»: up to three receipts an admin attaches to a paid payout (ADR-0024)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.sales.models import PayoutProof, PayoutRequest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.sales_factory import make_request, make_sale

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/sales/payouts"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"\x00" * 64


def _key(n: int) -> dict[str, str]:
    return {"Idempotency-Key": f"test-admin-payout-proof-{n:06d}"}


def _file(name: str) -> dict[str, str]:
    return {"X-File-Name": quote(name), "Content-Type": "application/octet-stream"}


async def _paid(db: AsyncSession, status: str = "paid") -> PayoutRequest:
    sale = await make_sale(db, status="payout", payout_to="card", payout_uzs=Decimal(147_400))
    return await make_request(db, sale, status=status)


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    rid: str,
    body: bytes,
    n: int,
    *,
    name: str = "чек.png",
) -> tuple[int, dict[str, object]]:
    r = await client.post(
        f"{BASE}/{rid}/proofs", content=body, headers={**headers, **_key(n), **_file(name)}
    )
    return r.status_code, r.json()


async def test_an_admin_attaches_receipts_to_a_paid_payout_and_reads_them_back(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    request = await _paid(db_session)
    status, body = await _upload(integration_client, h, request.id, PNG, 1, name="чек Humo.png")
    assert status == 200, body
    [proof] = body["proofs"]  # type: ignore[misc]
    assert proof["name"] == "чек Humo.png"
    assert proof["content_type"] == "image/png"
    assert proof["size"] == len(PNG)
    assert proof["uploaded_by"]["id"] is not None
    assert proof["delete_until"] is not None
    got = await integration_client.get(f"{BASE}/{request.id}/proofs/{proof['id']}", headers=h)
    assert got.status_code == 200
    assert got.content == PNG
    assert got.headers["content-type"] == "image/png"
    assert got.headers["cache-control"] == "no-store"
    assert got.headers["x-content-type-options"] == "nosniff"
    detail = await integration_client.get(f"{BASE}/{request.id}", headers=h)
    assert [p["id"] for p in detail.json()["proofs"]] == [proof["id"]]
    actions = await db_session.scalars(select(AdminAuditLog.action))
    assert "sales.payout.proof.add" in actions.all()


async def test_the_type_comes_from_the_bytes_not_the_name(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    request = await _paid(db_session)
    kinds = []
    for n, data in enumerate((JPEG, WEBP, PDF), start=1):
        status, body = await _upload(integration_client, h, request.id, data, n, name="x.png")
        assert status == 200, body
        kinds.append(body["proofs"][-1]["content_type"])  # type: ignore[index]
    assert kinds == ["image/jpeg", "image/webp", "application/pdf"]


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "proof_empty"),
        (b"<html><script>alert(1)</script>", "proof_type"),
        (PNG + b"\x00" * (5 * 1024 * 1024), "proof_too_large"),
    ],
    ids=["empty", "html", "large"],
)
async def test_an_empty_odd_or_oversized_file_is_refused(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    admin_headers: Headers,
    data: bytes,
    code: str,
) -> None:
    h = await admin_headers()
    request = await _paid(db_session)
    status, body = await _upload(integration_client, h, request.id, data, 1)
    assert (status, body["code"]) == (422, code)
    assert (await db_session.scalars(select(PayoutProof.id))).all() == []


async def test_three_receipts_at_most(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    request = await _paid(db_session)
    for n in (1, 2, 3):
        assert (await _upload(integration_client, h, request.id, PNG, n))[0] == 200
    status, body = await _upload(integration_client, h, request.id, PNG, 4)
    assert (status, body["code"]) == (409, "proof_limit")


async def test_only_a_paid_payout_takes_receipts(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    request = await _paid(db_session, status="to_pay")
    status, body = await _upload(integration_client, h, request.id, PNG, 1)
    assert (status, body["code"]) == (409, "payout_not_paid")


async def test_the_same_key_replays_the_upload_instead_of_adding_a_second(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    request = await _paid(db_session)
    first = await _upload(integration_client, h, request.id, PNG, 1)
    again = await _upload(integration_client, h, request.id, PNG, 1)
    assert first == again
    assert len((await db_session.scalars(select(PayoutProof.id))).all()) == 1
    other = await _upload(integration_client, h, request.id, JPEG, 1)
    assert (other[0], other[1]["code"]) == (409, "idempotency_mismatch")


async def test_a_receipt_can_be_deleted_for_ten_minutes_only(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    request = await _paid(db_session)
    _, body = await _upload(integration_client, h, request.id, PNG, 1)
    _, body = await _upload(integration_client, h, request.id, JPEG, 2)
    fresh, old = (p["id"] for p in body["proofs"])  # type: ignore[attr-defined]
    await db_session.execute(
        update(PayoutProof)
        .where(PayoutProof.id == old)
        .values(created_at=PayoutProof.created_at - timedelta(minutes=11))
    )
    await db_session.commit()
    gone = await integration_client.delete(
        f"{BASE}/{request.id}/proofs/{fresh}", headers={**h, **_key(3)}
    )
    assert gone.status_code == 200, gone.text
    assert [p["id"] for p in gone.json()["proofs"]] == [old]
    assert gone.json()["proofs"][0]["delete_until"] is None
    kept = await integration_client.delete(
        f"{BASE}/{request.id}/proofs/{old}", headers={**h, **_key(4)}
    )
    assert (kept.status_code, kept.json()["code"]) == (409, "proof_delete_expired")
    actions = await db_session.scalars(select(AdminAuditLog.action))
    assert "sales.payout.proof.delete" in actions.all()


async def test_a_receipt_of_another_payout_is_not_found(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h = await admin_headers()
    mine, other = await _paid(db_session), await _paid(db_session)
    _, body = await _upload(integration_client, h, mine.id, PNG, 1)
    pid = body["proofs"][0]["id"]  # type: ignore[index]
    got = await integration_client.get(f"{BASE}/{other.id}/proofs/{pid}", headers=h)
    assert got.status_code == 404


async def test_a_customer_never_reaches_a_receipt(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    admin_headers: Headers,
    customer_headers: Headers,
) -> None:
    request = await _paid(db_session)
    _, body = await _upload(integration_client, await admin_headers(), request.id, PNG, 1)
    pid = body["proofs"][0]["id"]  # type: ignore[index]
    customer = await customer_headers()
    got = await integration_client.get(f"{BASE}/{request.id}/proofs/{pid}", headers=customer)
    assert got.status_code == 403
    status, _ = await _upload(integration_client, customer, request.id, PNG, 2)
    assert status == 403
