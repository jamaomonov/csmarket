"""The worker: drain the Postgres-native queues.

Two queues in the product: ``orders`` (M4a) -- rows in ``paid`` are claimable
(``FOR UPDATE SKIP LOCKED``), the transaction that writes ``paid`` also
``NOTIFY orders``; its drain buys each claimed order at Waxpeer
(``orders.buying.drain_paid``) -- and ``emails`` (M4b) -- due ``email_outbox`` rows,
``NOTIFY emails`` with each insert; its drain sends them
(``notifications.sender.drain_emails``). Everything here is parameterised by
:class:`Queue` so a second queue is one more entry in ``_queues()``, never a
copy of the loop.

Each queue runs in its **own task**, on its own loop, so a slow queue delays
only itself. That is not tidiness: ``asyncio.gather`` returns with its slowest
member, so draining two queues in one awaited call would make the slower
drain's duration the other queue's polling period — a slow external call on a
second queue would stall every paid order behind it for as long as that took.

LISTEN gives instant wake-ups; a lazy poll tick (``worker_poll_seconds``)
catches notifications lost to restarts. A notification on **either** channel
wakes **every** queue — an empty queue costs one indexed query and returns,
which is far cheaper than routing wake-ups by channel and getting the routing
wrong. Each queue nonetheless owns its own ``asyncio.Event``: one shared event
between two consumers is a lost wake-up, because the first to return clears the
flag the second has not read yet.

The rows in the queue tables are the queues — this process holds no state worth
preserving and can be killed at any moment: row locks die with the connection
and the next tick reclaims the work.

Run as: ``python -m csmarket_worker.consumer``.
"""

from __future__ import annotations

import asyncio
import signal
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import asyncpg  # type: ignore[import-untyped]  # no bundled stubs
from csmarket.core.config import Settings, get_settings
from csmarket.core.db import get_engine
from csmarket.core.logging import configure_logging, get_logger
from csmarket.core.observability import init_sentry

# Every model the drains may touch, so the mappers and foreign keys resolve.
from csmarket.modules.auth import models as _auth_models  # noqa: F401
from csmarket.modules.click import models as _click_models  # noqa: F401
from csmarket.modules.fx import models as _fx_models  # noqa: F401
from csmarket.modules.notifications.api import EMAILS_CHANNEL, drain_emails
from csmarket.modules.orders.api import ORDERS_CHANNEL, drain_checks, drain_paid
from csmarket.modules.payme import models as _payme_models  # noqa: F401
from csmarket.modules.payments import models as _payments_models  # noqa: F401
from csmarket.modules.skins import models as _skins_models  # noqa: F401
from csmarket.modules.skinslink import models as _skinslink_models  # noqa: F401
from csmarket.modules.skinslink.api import SKINSLINK_CHANNEL
from csmarket.modules.users import models as _users_models  # noqa: F401
from csmarket.modules.uzum import models as _uzum_models  # noqa: F401
from csmarket.modules.wallet import models as _wallet_models  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from csmarket_worker import shutdown
from csmarket_worker.metrics import start_metrics_server

configure_logging()
log = get_logger("csmarket.worker.consumer")

#: One drain of one queue. Both drains take ``(db, *, limit=...)`` and return
#: how many rows the batch claimed; the loop only needs "did that do
#: anything", so the limit stays each module's own decision.
Drain = Callable[[AsyncSession], Awaitable[int]]


@dataclass(frozen=True, slots=True)
class Queue:
    """One Postgres-native queue this process drains.

    Attributes:
        name: Short label for log lines. Not the table and not the channel.
        channel: The LISTEN channel its producer NOTIFYs on. Imported from
            the producing module, never respelled here — a channel spelled
            twice is a queue nobody drains and no test fails.
        drain: The module's claim-and-run function, behind its ``api`` facade.
        concurrency: Independent drainers to fan out per wake.
    """

    name: str
    channel: str
    drain: Drain
    concurrency: int


async def _drain_orders(db: AsyncSession) -> int:
    """Claim paid orders and buy them at Waxpeer.

    ``drain_paid`` builds the process's purchase client (``skins.api.trade_client``) only
    when it claimed something, so an empty poll costs one query and no client.
    """
    return await drain_paid(db)


async def _drain_emails(db: AsyncSession) -> int:
    """Send due letters from the email outbox (``notifications.sender.drain_emails``)."""
    return await drain_emails(db)


async def _drain_skinslink_checks(db: AsyncSession) -> int:
    """Ask Skinslink about the purchases its webhook named (``orders.drain_checks``)."""
    return await drain_checks(db)


def _queues(cfg: Settings) -> tuple[Queue, ...]:  # noqa: ARG001 -- a queue may read settings
    """The queues this process drains, in the order a wake drains them.

    ``orders``: two drainers, so one Waxpeer call that hangs to its timeout stalls one
    drainer, not every paid order. ``emails``: one drainer — letters are not urgent to the
    second, and one sender keeps the provider's rate limit far away. ``skinslink``: one
    drainer — a status check is a single cheap read. Each channel constant
    comes from the producing module's ``api`` — a channel spelled twice is a queue nobody
    drains and no test fails.
    """
    return (
        Queue(name="orders", channel=ORDERS_CHANNEL, drain=_drain_orders, concurrency=2),
        Queue(name="emails", channel=EMAILS_CHANNEL, drain=_drain_emails, concurrency=1),
        Queue(
            name="skinslink",
            channel=SKINSLINK_CHANNEL,
            drain=_drain_skinslink_checks,
            concurrency=1,
        ),
    )


def raw_dsn(url: str) -> str:
    """Strip SQLAlchemy's ``+asyncpg`` driver suffix for a bare asyncpg DSN."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _wait_for_wake_or_tick(
    wake: asyncio.Event, stop: asyncio.Event, *, seconds: float
) -> None:
    """Return on whichever comes first: a NOTIFY wake-up, a stop signal, or the poll tick.

    Consumes (clears) ``wake`` before returning so a notification that lands
    mid-tick doesn't immediately re-fire the next wait -- the caller is about
    to drain anyway, so the signal has done its job.
    """
    wake_wait = asyncio.create_task(wake.wait())
    stop_wait = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait(
            {wake_wait, stop_wait}, timeout=seconds, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for task in (wake_wait, stop_wait):
            if not task.done():
                task.cancel()
        # Let cancellation actually land instead of leaving these to warn
        # "Task was destroyed but it is pending" at garbage-collection time.
        await asyncio.gather(wake_wait, stop_wait, return_exceptions=True)
    if wake.is_set():
        wake.clear()


class ListenerManager:
    """Owns one asyncpg LISTEN connection, on one channel, and its reconnect
    story.

    One instance per :class:`Queue`, parameterised rather than duplicated: two
    copies of this class would be two copies of the never-raise contract
    below, and the second copy is where it stops being true.

    LISTEN is a pure accelerant: it wakes the consumer loop the instant a
    task lands instead of waiting out the poll tick. It is never the queue's
    only path -- the poll tick is what makes a dropped connection self-heal
    without anyone paging, because ``ensure()`` is retried once per tick.
    Every failure inside ``ensure()`` is therefore swallowed and logged,
    never raised: a Postgres blip must degrade the worker to "polls every N
    seconds", not crash the process holding the actual queue drain.
    """

    def __init__(
        self,
        dsn: str,
        wakes: Sequence[asyncio.Event],
        *,
        channel: str,
        connect: Callable[[str], Awaitable[asyncpg.Connection]] = asyncpg.connect,
    ) -> None:
        self._dsn = dsn
        self._wakes = tuple(wakes)
        self._channel = channel
        self._connect = connect
        self._conn: asyncpg.Connection | None = None

    @property
    def connected(self) -> bool:
        """Whether a live LISTEN connection is currently held."""
        return self._conn is not None and not self._conn.is_closed()

    async def ensure(self) -> None:
        """(Re)establish the LISTEN connection if it is missing or dead.

        Never raises -- see the class docstring. A caller that wants to know
        whether LISTEN is actually up reads :attr:`connected` afterwards.
        """
        if self.connected:
            return
        self._conn = None
        try:
            conn = await self._connect(self._dsn)
            await conn.add_listener(self._channel, self._on_notify)
        except Exception:  # degrade to polling, never crash the loop
            log.exception("worker.consumer.listen_failed", channel=self._channel)
            return
        self._conn = conn

    def _on_notify(
        self,
        connection: object,  # noqa: ARG002 -- asyncpg's fixed callback signature
        pid: int,  # noqa: ARG002
        channel: str,  # noqa: ARG002
        payload: object,  # noqa: ARG002
    ) -> None:
        """Wake every queue's loop.

        The notification carries no information the loop needs -- each queue's
        table is re-queried on wake, so this is a pure signal, not a message.
        Every listener sets **every** queue's event, which is why one NOTIFY
        drains both queues: an empty one answers 0 on its first claim and
        returns, which costs less than routing wake-ups by channel.

        One event *per queue* rather than one shared between them, because
        ``_wait_for_wake_or_tick`` consumes what it waited on: with a single
        event the first loop to return clears the flag, and a second loop that
        was still draining when the NOTIFY landed waits out its whole tick for
        a signal that has already been thrown away.
        """
        for wake in self._wakes:
            wake.set()

    async def close(self) -> None:
        """Close the LISTEN connection, if any. Idempotent."""
        if self._conn is None:
            return
        conn, self._conn = self._conn, None
        await conn.close()


async def _drain_until_dry(session_factory: async_sessionmaker[AsyncSession], queue: Queue) -> None:
    """One drainer: claim-run-commit batches on its own session until dry.

    A session per drainer is mandatory, not tidiness: ``AsyncSession`` is not
    safe under concurrent use, so drainers sharing one would interleave
    statements on a single connection.

    Drain until dry: one NOTIFY or tick may cover more pending rows than a
    single batch (limit=20), so keep claiming until a batch comes back empty.
    Commit after every batch -- the invariant a crash must preserve is "loses
    nothing but row locks", not "loses nothing".
    """
    async with session_factory() as db:
        try:
            while await queue.drain(db) > 0:
                await db.commit()
            await db.commit()
        except Exception:
            # Outer belt for infra failures (DB down, a deadlock, etc.). A
            # poisoned individual row is contained inside each drain's own
            # per-row savepoint, and any per-row work *after* that savepoint
            # must catch its own exceptions for the same reason: a crash
            # escaping it would roll this batch back and be re-run and
            # re-crashed every tick. So a poisoned row should not reach here;
            # if one does it is a bug in that containment, not a row we can
            # drop.
            #
            # Rolling back loses only this drainer's uncommitted batch: its
            # rows stay claimable and the next tick reclaims them.
            log.exception("worker.consumer.drain_failed", queue=queue.name)
            await db.rollback()


async def _drain_all(session_factory: async_sessionmaker[AsyncSession], queue: Queue) -> None:
    """Run one queue's drainers, all of them, to completion.

    One queue, because the caller is that queue's own task: a ``gather`` that
    spanned several returns with its slowest member, which is how a slow queue
    would become every other queue's polling period.

    No coordination between drainers by design: ``FOR UPDATE SKIP LOCKED``
    makes their claims disjoint, so the only thing parallelism changes is that
    an external call that hangs for 20s stalls one drainer instead of the whole
    queue.

    ``return_exceptions=True`` is what makes "each drainer is isolated"
    literally true. ``_drain_until_dry`` handles what happens *inside* the
    drain, but its own cleanup can still raise -- a ``rollback`` or the
    session ``__aexit__`` on a connection that died. A bare ``gather``
    re-raises that immediately and abandons the sibling drainers mid-task,
    taking the whole tick down with one bad connection.
    """
    results = await asyncio.gather(
        *(_drain_until_dry(session_factory, queue) for _ in range(queue.concurrency)),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            # Type + first line only, never repr(): a SQLAlchemy error
            # stringifies with the statement and its bound parameters, and
            # those go to Loki (AGENTS.md §9). Same discipline as
            # :func:`shutdown.error_detail`.
            message = str(result).strip().splitlines()
            log.error(
                "worker.consumer.drainer_crashed",
                queue=queue.name,
                error=f"{type(result).__name__}: {message[0] if message else ''}"[:200],
            )


async def _queue_loop(
    session_factory: async_sessionmaker[AsyncSession],
    queue: Queue,
    *,
    listener: ListenerManager,
    wake: asyncio.Event,
    stop: asyncio.Event,
    poll_seconds: float,
) -> None:
    """One queue's whole life: wake, drain, repeat, until told to stop.

    Each queue gets one of these as its **own task**. That is the fix for a
    real coupling rather than a tidiness preference: with two queues drained
    inside one awaited ``gather``, the call returned only when the slowest
    drainer of either queue did, so the slower drain's duration became the
    other queue's polling period. Measured with fakes, a 3 s drain on one
    queue cut the other's drains in a 6 s window from 116 to 8; the real shape
    is a slow external call on one queue with every paid order waiting behind
    it.

    The listener is ensured here, once per iteration, for the same reason it
    always was: no backoff on a failed LISTEN, because the fixed poll tick IS
    the retry cadence and the queue's actual guarantee of progress. A LISTEN
    connection can also go stale silently -- nothing keepalives it -- in which
    case wake-ups stop arriving and the tick is the bound on latency until
    ``ensure()`` notices.

    Args:
        session_factory: Per-drainer session factory.
        queue: What to drain, and how wide.
        listener: This queue's LISTEN connection, re-ensured every iteration.
        wake: This queue's own event. Every listener sets every queue's.
        stop: Shared shutdown signal.
        poll_seconds: The tick.
    """
    while not stop.is_set():
        await listener.ensure()
        await _wait_for_wake_or_tick(wake, stop, seconds=poll_seconds)
        if stop.is_set():
            break
        await _drain_all(session_factory, queue)


async def run() -> int:
    """Start one loop per queue, supervise them, and shut down inside a budget.

    Nothing here is stateful across iterations except the connections
    themselves -- kill the process at any point and the next start (or another
    replica) picks up exactly where the row locks left off.

    Returns:
        A process exit code: ``0`` for an ordinary stop, ``1`` when a queue
        loop died. Non-zero on purpose — a queue that stopped draining must
        take the container down so ``restart: unless-stopped`` restarts it,
        because the alternative is a healthy-looking process with the money
        path stopped.
    """
    cfg = get_settings()
    # Every queue drain runs here, so this is the half of the system where an
    # unreported crash costs money.
    # No ASGI integrations: nothing here serves a request.
    init_sentry(cfg, integrations="none")
    start_metrics_server()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    queues = _queues(cfg)
    # One event per queue, and every listener sets all of them -- see
    # ``_on_notify`` for why both halves of that sentence matter.
    wakes = tuple(asyncio.Event() for _ in queues)
    dsn = raw_dsn(cfg.database_url)
    listeners = tuple(ListenerManager(dsn, wakes, channel=queue.channel) for queue in queues)
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    log.info(
        "worker.consumer.started",
        poll_seconds=cfg.worker_poll_seconds,
        # A name -> concurrency map, one entry per registered queue.
        queues={queue.name: queue.concurrency for queue in queues},
    )

    loops = [
        asyncio.create_task(
            _queue_loop(
                session_factory,
                queue,
                listener=listener,
                wake=wake,
                stop=stop,
                poll_seconds=cfg.worker_poll_seconds,
            ),
            name=f"drain:{queue.name}",
        )
        for queue, wake, listener in zip(queues, wakes, listeners, strict=True)
    ]

    crashed = await shutdown.supervise(loops, stop=stop)

    # One budget for the whole shutdown, spent in order and never exceeded:
    # past Docker's grace period the rest of this function does not happen.
    deadline = time.monotonic() + shutdown.SHUTDOWN_BUDGET_SECONDS
    _done, still_draining = (
        await asyncio.wait(
            loops,
            timeout=min(shutdown.SHUTDOWN_DRAIN_SECONDS, shutdown.remaining(deadline)),
        )
        if loops
        else (set(), set())
    )
    if still_draining:
        # Bounded: a loop caught mid-drain finishes its batch if it can, and is
        # otherwise cancelled by ``asyncio.run`` on the way out. Cancelling a
        # drain is safe by construction -- it rolls back an uncommitted batch
        # and its rows stay claimable ("loses nothing but row locks").
        log.info(
            "worker.consumer.shutdown_left_draining",
            queues=[task.get_name() for task in still_draining],
            waited_seconds=shutdown.SHUTDOWN_DRAIN_SECONDS,
        )

    # ``exclude=loops`` or the still-draining loop is waited on twice, once
    # here under a name and once as a stray -- which is how the two five-second
    # budgets became one ten-second total.
    await shutdown.await_stray_tasks(timeout=shutdown.remaining(deadline), exclude=loops)
    for listener in listeners:
        await listener.close()
    log.info("worker.consumer.stopped", crashed=crashed)
    return 1 if crashed else 0


if __name__ == "__main__":
    # ``sys.exit`` on the return value, so a dead queue loop is a container
    # restart rather than a process that stays up one queue short.
    sys.exit(asyncio.run(run()))
