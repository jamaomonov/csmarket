"""Skinslink deposits: users sell skins to our balance at Skinslink (spec 2026-10-08).

``POST /merchant/inventory`` prices the user's tradable CS2 items — a 5-minute snapshot that
``create-deposit`` prices from; ``POST /merchant/create-deposit`` has a Skinslink bot send the
user one trade offer; ``GET /merchant/deposit/status`` says where the deposit is. Same
envelope, error types and metric as the purchase calls (:mod:`.client`). The trade token is
sent, never logged; error bodies are never logged (the refusal ``code`` only).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol

from csmarket.core.config import Settings
from csmarket.modules.skinslink.client import (
    LINK_ERROR_CODES,
    SkinslinkClient,
    SkinslinkError,
    SkinslinkUnavailableError,
    _decimal,
    _str,
)

#: Refusals that mean "the prices moved": the inventory must be read again.
PRICE_CODES = frozenset({"inventory_reload", "item_specified_price_not_found"})
#: Refusals about the user's Steam account (Get Inventory and Create Deposit share them).
STEAM_ACCOUNT_CODES = LINK_ERROR_CODES
#: Skinslink prices to 1/1000 $; a floor rounded down never refuses the price we quoted.
_THREE_PLACES = Decimal("0.001")


@dataclass(frozen=True)
class InventoryItem:
    """One tradable item Skinslink accepts now, priced in USD (``items[]``)."""

    id: str
    name: str
    price_usd: Decimal
    image_url: str | None
    exterior: str | None
    rarity: str | None
    rarity_color: str | None


@dataclass(frozen=True)
class Inventory:
    """The priced inventory and the most items one deposit may carry."""

    items: list[InventoryItem]
    max_items: int


@dataclass(frozen=True)
class Deposit:
    """A deposit as Skinslink reports it (Create Deposit / Deposit Status).

    ``amount_usd`` comes with Create Deposit only; ``hold_end_date`` with ``hold``;
    ``fail_reason`` with ``failed`` / ``canceled`` / ``reverted``.
    """

    id: int
    merchant_tx_id: str | None
    status: str
    amount_usd: Decimal | None
    bot_name: str | None
    trade_offer_id: str | None
    offer_expiry_at: str | None
    hold_end_date: str | None
    fail_reason: str | None


class DepositClient(Protocol):
    """What ``sales`` needs from Skinslink (the real client or a test double)."""

    async def inventory(self, *, partner: int, token: str) -> Inventory:
        """The user's priced, tradable inventory."""
        ...

    async def create_deposit(
        self,
        *,
        merchant_tx_id: str,
        partner: int,
        token: str,
        asset_ids: Sequence[str],
        min_prices: Mapping[str, Decimal],
    ) -> Deposit:
        """Have a bot send the user one offer for ``asset_ids``."""
        ...

    async def deposit_status(self, *, merchant_tx_id: str) -> Deposit | None:
        """The deposit under ``merchant_tx_id``, or ``None`` when Skinslink has none."""
        ...


# Any: one JSON object of Skinslink's, read field by field.
def _inventory_item(raw: Mapping[str, Any]) -> InventoryItem | None:
    """An inventory card, or ``None`` when its id, name or price is unusable."""
    raw_id = raw.get("id")
    item_id = str(raw_id) if isinstance(raw_id, int | str) and not isinstance(raw_id, bool) else ""
    name = _str(raw.get("name"))
    price = _decimal(raw.get("price"))
    if not item_id or name is None or price is None or price <= 0:
        return None
    return InventoryItem(
        id=item_id,
        name=name,
        price_usd=price,
        image_url=_str(raw.get("image_url")),
        exterior=_str(raw.get("exterior")),
        rarity=_str(raw.get("rarity")),
        rarity_color=_str(raw.get("rarity_color")),
    )


def _deposit(raw: object) -> Deposit:
    """A deposit answer; one without an integer id or a status is an outage, not a deposit."""
    if not isinstance(raw, Mapping):
        raise SkinslinkUnavailableError("unexpected body")
    did = raw.get("id")
    status = _str(raw.get("status"))
    if not isinstance(did, int) or isinstance(did, bool) or status is None:
        raise SkinslinkUnavailableError("unexpected body")
    return Deposit(
        id=did,
        merchant_tx_id=_str(raw.get("merchant_tx_id")),
        status=status,
        amount_usd=_decimal(raw.get("amount")),
        bot_name=_str(raw.get("bot_name")),
        trade_offer_id=_str(raw.get("trade_offer_id")),
        offer_expiry_at=_str(raw.get("trade_offer_expiry_at")),
        hold_end_date=_str(raw.get("hold_end_date")),
        fail_reason=_str(raw.get("fail_reason")),
    )


class SkinslinkDepositClient(SkinslinkClient):
    """The merchant client with the deposit calls; inject ``client`` in tests."""

    async def inventory(self, *, partner: int, token: str) -> Inventory:
        """``POST /merchant/inventory`` (CS2). Unreadable cards are skipped.

        Raises:
            SkinslinkError: A refusal (``code``: a Steam account code, ``inventory_reload``).
            SkinslinkForbiddenError: HTTP 403.
            SkinslinkUnavailableError: Transport, 408/5xx, 429 or an unreadable body.
        """
        data = await self._request(
            "POST",
            "/merchant/inventory",
            endpoint="inventory",
            json_body={"game": "csgo", "partner": partner, "token": token},
        )
        if not isinstance(data, Mapping) or not isinstance(data.get("items"), list):
            raise SkinslinkUnavailableError("unexpected body")
        max_items = data.get("max_items")
        if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items < 1:
            raise SkinslinkUnavailableError("unexpected body")
        items = [
            item
            for raw in data["items"]
            if isinstance(raw, Mapping) and (item := _inventory_item(raw)) is not None
        ]
        return Inventory(items=items, max_items=max_items)

    async def create_deposit(
        self,
        *,
        merchant_tx_id: str,
        partner: int,
        token: str,
        asset_ids: Sequence[str],
        min_prices: Mapping[str, Decimal],
    ) -> Deposit:
        """``POST /merchant/create-deposit``; ``min_prices`` (USD) rounded down to 0.001.

        Raises:
            SkinslinkError: A refusal — ``code`` one of :data:`PRICE_CODES`, a Steam account
                code, ``too_many_items``; ``status`` 409 (``already_exists``) when the
                ``merchant_tx_id`` was used: the deposit exists, read it by status.
            SkinslinkForbiddenError: HTTP 403.
            SkinslinkUnavailableError: The deposit may exist: resolve through the status.
        """
        data = await self._request(
            "POST",
            "/merchant/create-deposit",
            endpoint="deposit",
            json_body={
                "merchant_tx_id": merchant_tx_id,
                "game": "csgo",
                "partner": partner,
                "token": token,
                "asset_ids": list(asset_ids),
                "min_prices": {
                    asset: float(floor.quantize(_THREE_PLACES, rounding=ROUND_DOWN))
                    for asset, floor in min_prices.items()
                },
            },
        )
        return _deposit(data)

    async def deposit_status(self, *, merchant_tx_id: str) -> Deposit | None:
        """``GET /merchant/deposit/status``; ``None`` when Skinslink has no such deposit."""
        try:
            data = await self._request(
                "GET",
                "/merchant/deposit/status",
                endpoint="deposit_status",
                params={"merchant_tx_id": merchant_tx_id},
            )
        except SkinslinkError as exc:
            if exc.status == 404:
                return None
            raise
        return _deposit(data)


def deposit_client_for(settings: Settings, *, timeout_seconds: float) -> SkinslinkDepositClient:
    """The process's deposit client with ``timeout_seconds`` per call."""
    return SkinslinkDepositClient(
        api_key=settings.skinslink_api_key,
        base_url=settings.skinslink_base_url,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "PRICE_CODES",
    "STEAM_ACCOUNT_CODES",
    "Deposit",
    "DepositClient",
    "Inventory",
    "InventoryItem",
    "SkinslinkDepositClient",
    "deposit_client_for",
]
