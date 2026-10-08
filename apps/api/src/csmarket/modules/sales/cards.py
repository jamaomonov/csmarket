"""Saved payout cards (spec 2026-10-08 §2, §4): checked, encrypted, shown by the last four.

A number is checked — 16 ASCII digits, the type's prefix, Luhn — and stored encrypted under
:data:`~csmarket.modules.sales.models.CARD_PURPOSE`; only ``last4`` is ever logged, listed,
replayed or put in a letter. The full number leaves the database through
:func:`reveal_number` alone, which only the admin's audited reveal calls. At most
:data:`MAX_LIVE_CARDS` live cards per user (the user row is locked while counting, so two
adds cannot both pass). A delete is soft: a paid request keeps pointing at its card.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.crypto import decrypt, encrypt
from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.modules.sales.models import CARD_PURPOSE, PayoutCard
from csmarket.modules.sales.rules import CardType
from csmarket.modules.users.api import User

log = get_logger("csmarket.sales.cards")

MAX_LIVE_CARDS = 3
_LENGTH = 16
#: The first digits of each card type we pay to (Uzcard, Humo, Uzum Visa).
_PREFIXES: dict[str, tuple[str, ...]] = {
    "uzcard": ("8600", "5614"),
    "humo": ("9860",),
    "uzum_visa": ("4",),
}


def luhn_ok(digits: str) -> bool:
    """Whether ``digits`` pass the Luhn check (every second digit from the right doubled)."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        total += sum(divmod(digit * 2, 10)) if index % 2 == 1 else digit
    return total % 10 == 0


def card_digits(card_type: str, raw: str) -> str:
    """The 16 digits of ``raw`` (spaces and dashes dropped) if they fit ``card_type``.

    Raises:
        ValidationError: ``code="card_invalid"`` — the message never contains the number.
    """
    digits = raw.replace(" ", "").replace("-", "")
    prefixes = _PREFIXES.get(card_type)
    fits = (
        prefixes is not None
        and len(digits) == _LENGTH
        and digits.isascii()
        and digits.isdigit()
        and digits.startswith(prefixes)
        and luhn_ok(digits)
    )
    if not fits:
        raise ValidationError("this card number is not valid", code="card_invalid")
    return digits


def masked(last4: str) -> str:
    """How a card is shown: ``•••• 9015``."""
    return f"•••• {last4}"


async def live_cards(db: AsyncSession, user_id: str) -> list[PayoutCard]:
    """The user's live cards, oldest first."""
    rows = await db.scalars(
        select(PayoutCard)
        .where(PayoutCard.user_id == user_id, PayoutCard.deleted_at.is_(None))
        .order_by(PayoutCard.created_at, PayoutCard.id)
    )
    return list(rows.all())


async def add_card(
    db: AsyncSession, *, user_id: str, card_type: CardType, raw_number: str
) -> PayoutCard:
    """Check, encrypt and save a card; flushes, never commits.

    Raises:
        ValidationError: ``card_invalid``.
        ConflictError: ``cards_limit`` — the user already has :data:`MAX_LIVE_CARDS`.
    """
    digits = card_digits(card_type, raw_number)
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    if len(await live_cards(db, user_id)) >= MAX_LIVE_CARDS:
        raise ConflictError("you already have 3 saved cards", code="cards_limit")
    enc, nonce = encrypt(digits, purpose=CARD_PURPOSE)
    card = PayoutCard(
        id=new_id(),
        user_id=user_id,
        type=card_type,
        number_enc=enc,
        number_nonce=nonce,
        last4=digits[-4:],
    )
    db.add(card)
    await db.flush()
    log.info("sales.card.added", card_type=card_type, last4=card.last4)
    return card


async def owned_card(db: AsyncSession, *, user_id: str, card_id: str) -> PayoutCard:
    """The user's live card ``card_id``.

    Raises:
        NotFoundError: Another user's, unknown or deleted.
    """
    card = await db.scalar(
        select(PayoutCard).where(
            PayoutCard.id == card_id,
            PayoutCard.user_id == user_id,
            PayoutCard.deleted_at.is_(None),
        )
    )
    if card is None:
        raise NotFoundError("card not found")
    return card


async def delete_card(db: AsyncSession, *, user_id: str, card_id: str) -> None:
    """Forget the user's card (soft); an already deleted one is left as it is. Flushes.

    Raises:
        NotFoundError: Another user's or unknown.
    """
    card = await db.scalar(
        select(PayoutCard).where(PayoutCard.id == card_id, PayoutCard.user_id == user_id)
    )
    if card is None:
        raise NotFoundError("card not found")
    if card.deleted_at is None:
        card.deleted_at = now()
        await db.flush()
        log.info("sales.card.deleted", last4=card.last4)


def reveal_number(card: PayoutCard) -> str:
    """The full number — for the admin's audited reveal only. PII: never log the result."""
    return decrypt(card.number_enc, card.number_nonce, purpose=CARD_PURPOSE)


__all__ = [
    "MAX_LIVE_CARDS",
    "add_card",
    "card_digits",
    "delete_card",
    "live_cards",
    "luhn_ok",
    "masked",
    "owned_card",
    "reveal_number",
]
