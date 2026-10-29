"""One poll tick over the desk's due deposits (the webhook only makes one due sooner)."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.desk.deposits import check_deposit, due_deposits
from csmarket.modules.skinslink.api import DepositClient

log = get_logger("csmarket.desk.poll")

SessionFactory = Callable[[], AsyncSession]


async def poll_deposits(db_factory: SessionFactory, client: DepositClient) -> int:
    """Ask about every due deposit, one session each; one failure never stops the tick.

    Returns:
        How many deposits the tick asked about.
    """
    async with db_factory() as db:
        due = await due_deposits(db, at=now())
        await db.commit()
    for deposit_id in due:
        try:
            async with db_factory() as db:
                await check_deposit(db, client, deposit_id=deposit_id)
        except Exception as exc:  # noqa: BLE001 -- one deposit must not stop the tick
            log.error("desk.poll_failed", error=type(exc).__name__)  # noqa: TRY400
    return len(due)


__all__ = ["poll_deposits"]
