"""A trader's inventory as Skinslink prices it, by trade link — for a new deal. One
``inventory`` call, nothing held across it, nothing kept; the link is never logged. Skinslink
carries no picture, so each item takes our catalogue's, read after the call.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import get_settings
from csmarket.core.errors import ConflictError, UpstreamUnavailableError
from csmarket.core.logging import get_logger
from csmarket.modules.desk.money import plain
from csmarket.modules.desk.schemas import InventoryItemOut, InventoryOut
from csmarket.modules.skins.api import images_by_name, steam_image
from csmarket.modules.skinslink.api import (
    STEAM_ACCOUNT_CODES,
    DepositClient,
    SkinslinkError,
    SkinslinkUnavailableError,
)
from csmarket.modules.users.api import parse_tradelink

log = get_logger("csmarket.desk.inventory")


class DeskUnavailableError(UpstreamUnavailableError):
    """Skinslink refused or could not be asked; expected, a warning only."""

    status_code = 503
    report = False
    type_uri = "https://csmarket.uz/errors/desk-unavailable"
    title = "Skinslink unavailable"


def unavailable() -> DeskUnavailableError:
    """The one 503 the desk answers for Skinslink."""
    return DeskUnavailableError("Skinslink is unavailable", code="desk_unavailable")


def refused(exc: SkinslinkError) -> Exception:
    """A Steam account refusal → 409 ``steam_refused`` with ``reason``; anything else → 503."""
    if exc.code in STEAM_ACCOUNT_CODES:
        return ConflictError(
            "Steam does not let this account trade", code="steam_refused", reason=exc.code
        )
    log.warning("desk.skinslink.refused", code=exc.code)
    return unavailable()


async def load_inventory(db: AsyncSession, client: DepositClient, trade_link: str) -> InventoryOut:
    """The trader's tradable items Skinslink takes, dearest first, with our pictures.

    ``db`` is first used after the Skinslink call, so no connection is held across it.

    Raises:
        ValidationError: ``trade_link_invalid``.
        ConflictError: ``steam_refused``.
        DeskUnavailableError: ``desk_unavailable``.
    """
    link = parse_tradelink(trade_link)
    try:
        inv = await client.inventory(partner=link.partner, token=link.token)
    except SkinslinkError as exc:
        raise refused(exc) from None
    except SkinslinkUnavailableError as exc:
        log.warning("desk.skinslink.unavailable", error=type(exc).__name__)
        raise unavailable() from None
    items = sorted(inv.items, key=lambda i: i.price_usd, reverse=True)
    ours = await images_by_name(db, (i.name for i in items if not i.image_url))
    host = get_settings().skins_image_host
    return InventoryOut(
        items=[
            InventoryItemOut(
                asset_id=i.id,
                name=i.name,
                image_url=steam_image(i.image_url or ours.get(i.name), host=host),
                price_usd=plain(i.price_usd) or "0",
            )
            for i in items
        ]
    )


__all__ = ["DeskUnavailableError", "load_inventory", "refused", "unavailable"]
