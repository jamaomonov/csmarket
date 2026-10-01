"""``record_job`` / ``read_job``: a JSON status in Redis, no TTL, advisory."""

from __future__ import annotations

import pytest
from csmarket.core.redis import get_redis
from csmarket.modules.skins.job_status import JOB_IMPORT, JOB_PRICE_SYNC, read_job, record_job

pytestmark = pytest.mark.asyncio


async def test_round_trip() -> None:
    await record_job(
        get_redis(), JOB_IMPORT, ok=True, counters={"files": 11, "rows": 35000, "changed": 12}
    )
    got = await read_job(get_redis(), JOB_IMPORT)
    assert got is not None
    assert got.ok
    assert got.counters["rows"] == 35000
    assert got.error is None


async def test_failure_keeps_the_error_label() -> None:
    await record_job(get_redis(), JOB_PRICE_SYNC, ok=False, counters={}, error="HTTPStatusError")
    got = await read_job(get_redis(), JOB_PRICE_SYNC)
    assert got is not None
    assert not got.ok
    assert got.error == "HTTPStatusError"


async def test_unknown_job_is_none() -> None:
    assert await read_job(get_redis(), "never-ran") is None


async def test_status_has_no_ttl() -> None:
    await record_job(get_redis(), JOB_IMPORT, ok=True, counters={})
    assert await get_redis().ttl("skins:job:import") == -1


async def test_garbage_value_reads_as_none() -> None:
    await get_redis().set("skins:job:import", "not json")
    assert await read_job(get_redis(), JOB_IMPORT) is None
