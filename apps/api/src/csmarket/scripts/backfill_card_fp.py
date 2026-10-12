"""Fill the fingerprint (``payout_cards.number_fp``) of cards saved before migration 0033.

Run once after the deploy that brings 0033, inside the api container (it needs the app key)::

    docker compose -f docker-compose.prod.yml exec api python -m csmarket.scripts.backfill_card_fp

Idempotent: it touches only cards without a fingerprint. It prints only how many it filled —
never a number, a last four or a fingerprint.
"""

from __future__ import annotations

import asyncio
import sys

# Registers the tables the sales models reference, as in the app.
import csmarket.modules.auth.models  # noqa: F401
from csmarket.core.db import dispose_engine, get_session_factory
from csmarket.modules.sales.cards import backfill_fingerprints


async def _main() -> int:
    factory = get_session_factory()
    try:
        async with factory() as db:
            filled = await backfill_fingerprints(db)
            await db.commit()
    finally:
        await dispose_engine()
    print(f"filled {filled}")
    return 0


def main() -> int:
    """CLI entrypoint."""
    return asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover - the CLI
    sys.exit(main())
