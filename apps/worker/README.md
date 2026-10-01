# apps/worker — csmarket background worker

Postgres-queue consumer. `src/csmarket_worker/consumer.py` drains the queues
registered in `_queues()`. The product has one, **`orders`** on `LISTEN orders`
(M4): rows in `paid` are claimable with `FOR UPDATE SKIP LOCKED`, and the
transaction that writes `paid` also `NOTIFY orders`. Concurrency is the
`worker_concurrency` setting.

**M0 registers no queues.** The process starts, listens for SIGTERM and exits
0, so the container runs from the first deploy. M4 adds
`Queue(name="orders", channel=ORDERS_QUEUE_CHANNEL, drain=drain_paid_orders, concurrency=cfg.worker_concurrency)`
to `_queues()`; the channel constant is imported from the module that NOTIFYs
it, never respelled here.

**Each queue runs in its own asyncio task**, with its own loop and its own
`asyncio.Event`. `asyncio.gather` returns with its slowest member, so draining
two queues in one awaited call would make the slower one the other's polling
period. Regression-tested in
`tests/test_consumer.py::test_a_slow_queue_does_not_pace_the_other`, which
measures the coupled shape as its own control rather than asserting a bare
number.

LISTEN is an accelerant, not the queue's only path: a poll tick
(`worker_poll_seconds`) catches notifications lost to a restart and retries a
dropped LISTEN connection. A notification on any channel wakes every queue —
an empty queue costs one indexed query — but each queue owns its own event,
because `_wait_for_wake_or_tick` consumes what it waited on and one shared
event between two consumers is a lost wake-up. Every wake fans out to that
queue's `concurrency` drainers, each on its own session; `SKIP LOCKED` keeps
their claims disjoint without coordination.

The rows are the queue — this process holds no state worth preserving and can
be killed at any moment; row locks die with the connection.

**A queue loop that dies takes the process with it.** `run()` supervises the
loop tasks: one that raises (or returns without a stop signal) is logged as
`worker.consumer.queue_loop_died` and `run()` exits **1**, so
`restart: unless-stopped` restarts the container instead of leaving a
healthy-looking process one queue short.

**Shutdown is one budget, not two.** `SHUTDOWN_BUDGET_SECONDS` (8) covers the
whole path from the stop signal to the last log line; a loop caught mid-drain
gets the first `SHUTDOWN_DRAIN_SECONDS` (3) of it and fire-and-forget sends get
whatever is left. Cancelling a drain is safe — it rolls the batch back and its
rows stay claimable. 8 and not 10 because Docker's default `stop_grace_period`
is 10 s and neither compose file overrides it for `worker`; raising the budget
past that means setting `stop_grace_period` first.

## Layout

- `consumer.py` — the queues: what they are, how they are woken, how they are
  drained, and `run()` wiring them together. `python -m csmarket_worker.consumer`
  exits 0 on SIGTERM and 1 when a queue loop dies.
- `shutdown.py` — when this process stops and how long it may take doing it:
  the supervision that turns a dead queue loop into a non-zero exit, and the
  one budget the whole shutdown path spends. It keeps the
  `csmarket.worker.consumer` logger name deliberately — event names are what
  Loki and Grafana read.

## Run locally

```bash
make dev-worker
```
