"""P2P cards and switches for the tests (spec 2026-10-19-p2p-topup)."""

from __future__ import annotations

from csmarket.modules.p2p.cards import seal_pan
from csmarket.modules.p2p.models import P2PCard
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.kassa_fee_factory import set_fees

#: A made-up Humo number; only its last four matter to the matching.
PAN = "9860000000004321"


async def make_card(
    db: AsyncSession,
    *,
    pan: str = PAN,
    holder: str = "TEST HOLDER",
    min_uzs: int = 10_000,
    max_uzs: int = 5_000_000,
    daily_limit_uzs: int | None = None,
    active: bool = True,
) -> P2PCard:
    """A committed card."""
    ciphertext, nonce = seal_pan(pan)
    card = P2PCard(
        label="test",
        pan_ciphertext=ciphertext,
        pan_nonce=nonce,
        pan_last4=pan[-4:],
        holder_name=holder,
        network="humo",
        active=active,
        min_amount_uzs=min_uzs,
        max_amount_uzs=max_uzs,
        daily_limit_uzs=daily_limit_uzs,
    )
    db.add(card)
    await db.commit()
    return card


async def p2p_on(db: AsyncSession) -> None:
    """Switch the P2P kassa on (it starts off)."""
    await set_fees(db, statuses={"p2p": "on"})
