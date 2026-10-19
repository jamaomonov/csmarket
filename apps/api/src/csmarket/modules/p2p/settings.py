"""The P2P settings row: the Telegram identities to trust and the buyer's limits."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.p2p.models import P2PSettings


async def load_settings(db: AsyncSession, *, lock: bool = False) -> P2PSettings:
    """The singleton row; created with the spec's limits if a fresh database lacks it."""
    row = await db.get(P2PSettings, 1, with_for_update=lock)
    if row is None:
        row = P2PSettings(
            id=1,
            min_amount_uzs=10_000,
            max_amount_uzs=5_000_000,
            daily_count=3,
            daily_amount_uzs=10_000_000,
        )
        db.add(row)
        await db.flush()
    return row


__all__ = ["load_settings"]
