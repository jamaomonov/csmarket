"""«Ask Skinslink about sale N» rows, drained by the worker's ``sales`` queue (spec §6).

The deposit webhook — after its signature — inserts a row and notifies in its transaction;
only a known sale id is queued (``merchant_tx_id`` is the sale's id), so a forged or stray id
queues nothing. The drain claims rows ``FOR UPDATE SKIP LOCKED``, deletes them and asks
Skinslink about each (``status.check_sale``). A failed ask is not retried by the row: the
poll (:mod:`.reconcile`) asks about every open sale anyway.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings, get_settings
from csmarket.core.logging import get_logger
from csmarket.modules.sales.models import SALES_CHANNEL, Sale, SaleCheck
from csmarket.modules.sales.status import check_sale
from csmarket.modules.skinslink.api import DepositClient, deposit_client_for

log = get_logger("csmarket.sales.checks")


async def enqueue_sale_check(db: AsyncSession, merchant_tx_id: object) -> bool:
    """Queue a check of the sale ``merchant_tx_id`` names; delivered when the caller commits.

    Returns:
        Whether a check was queued (``False``: not a sale id of ours).
    """
    if not isinstance(merchant_tx_id, str):
        return False
    try:
        sale_id = str(uuid.UUID(merchant_tx_id))
    except ValueError:
        return False
    if await db.scalar(select(Sale.id).where(Sale.id == sale_id)) is None:
        return False
    db.add(SaleCheck(sale_id=sale_id))
    await db.flush()
    await db.execute(select(func.pg_notify(SALES_CHANNEL, sale_id)))
    return True


async def claim_sale_checks(db: AsyncSession, *, limit: int = 20) -> list[str]:
    """Take up to ``limit`` queued checks, oldest first, and delete them; the caller commits.

    Returns:
        The sale ids to ask about (a sale queued twice is asked once).
    """
    rows = (
        await db.execute(
            select(SaleCheck.id, SaleCheck.sale_id)
            .order_by(SaleCheck.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not rows:
        return []
    await db.execute(delete(SaleCheck).where(SaleCheck.id.in_([r[0] for r in rows])))
    return list(dict.fromkeys(str(r[1]) for r in rows))


async def drain_sale_checks(
    db: AsyncSession,
    *,
    client: DepositClient | None = None,
    settings: Settings | None = None,
    limit: int = 20,
) -> int:
    """The worker's ``sales`` drain: take queued checks and ask Skinslink about each.

    Returns:
        How many checks were taken (0 = the queue is dry).
    """
    settings = settings or get_settings()
    ids = await claim_sale_checks(db, limit=limit)
    await db.commit()
    # The key, not the switches: open sales still settle after selling is switched off.
    if not ids or (client is None and not settings.skinslink_api_key):
        return len(ids)
    client = client or deposit_client_for(
        settings, timeout_seconds=settings.skinslink_request_timeout_seconds
    )
    for sale_id in ids:
        try:
            await check_sale(db, client, sale_id=sale_id)
        except Exception as exc:  # noqa: BLE001 -- one bad check must not stop the batch
            await db.rollback()
            log.error("sales.check_crashed", error=type(exc).__name__)  # noqa: TRY400
    return len(ids)


__all__ = ["claim_sale_checks", "drain_sale_checks", "enqueue_sale_check"]
