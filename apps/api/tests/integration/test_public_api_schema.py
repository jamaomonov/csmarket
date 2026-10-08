"""``api_keys`` and the API columns of ``orders`` (plan B, Task 1)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.public_api.models import ApiKey
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import build_order, make_item_and_rate
from tests.integration.payments_factory import make_user


def _key(user_id: str, **overrides: object) -> ApiKey:
    values: dict[str, object] = {"id": new_id(), "user_id": user_id, "token_hash": uuid4().hex}
    values.update(overrides)
    return ApiKey(**values)


async def test_key_defaults(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    key = _key(user.id)
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    assert key.pricing_profile == "retail"
    assert key.ip_allowlist == []
    assert key.last_used_at is None
    assert key.revoked_at is None


async def test_two_live_keys_for_one_user_are_refused(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    db_session.add_all([_key(user.id)])
    await db_session.commit()
    db_session.add(_key(user.id))
    with pytest.raises(IntegrityError, match="uq_api_keys_live_user"):
        await db_session.commit()


async def test_a_revoked_key_and_a_live_key_coexist(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    db_session.add_all([_key(user.id, revoked_at=datetime.now(UTC)), _key(user.id)])
    await db_session.commit()


async def test_unknown_pricing_profile_is_refused(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    db_session.add(_key(user.id, pricing_profile="free"))
    with pytest.raises(IntegrityError, match="ck_api_keys_pricing_profile"):
        await db_session.commit()


async def test_api_order_needs_its_key_and_client_id(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    item, fx = await make_item_and_rate(db_session)
    await build_order(db_session, user=user, item=item, fx=fx, channel="api")
    with pytest.raises(IntegrityError, match="ck_orders_channel_fields"):
        await db_session.commit()


async def test_site_order_must_have_no_key(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    key = _key(user.id)
    db_session.add(key)
    await db_session.commit()
    item, fx = await make_item_and_rate(db_session)
    await build_order(db_session, user=user, item=item, fx=fx, api_key_id=key.id)
    with pytest.raises(IntegrityError, match="ck_orders_channel_fields"):
        await db_session.commit()


async def test_client_order_id_is_unique_per_key(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    key = _key(user.id)
    db_session.add(key)
    await db_session.commit()
    item, fx = await make_item_and_rate(db_session)
    api = {
        "channel": "api",
        "api_key_id": key.id,
        "client_order_id": "c-1",
        "pricing_profile": "retail",
    }
    await build_order(db_session, user=user, item=item, fx=fx, **api)
    await db_session.commit()
    await build_order(db_session, user=user, item=item, fx=fx, **api)
    with pytest.raises(IntegrityError, match="uq_orders_api_key_id_client_order_id"):
        await db_session.commit()
