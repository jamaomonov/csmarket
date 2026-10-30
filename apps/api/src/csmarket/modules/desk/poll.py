"""One poll tick over the desk's due deposits (the webhook only makes one due sooner)."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.desk.deposits import PersonaLookup, check_deposit, due_deposits, fill_bot
from csmarket.modules.skinslink.api import DepositClient

log = get_logger("csmarket.desk.poll")

SessionFactory = Callable[[], AsyncSession]


async def poll_deposits(
    db_factory: SessionFactory, client: DepositClient, *, persona: PersonaLookup | None = None
) -> int:
    """Ask about every due deposit, one session each; one failure never stops the tick.

    With ``persona``, a deposit whose bot is known gets the bot's Steam name and avatar once.

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
                if persona is not None:
                    await fill_bot(db, deposit_id, persona)
        except Exception as exc:  # noqa: BLE001 -- one deposit must not stop the tick
            log.error("desk.poll_failed", error=type(exc).__name__)  # noqa: TRY400
    return len(due)


__all__ = ["poll_deposits"]
