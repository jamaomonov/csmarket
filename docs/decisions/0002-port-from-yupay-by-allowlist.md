# 0002. Port from YuPay by allow-list

- **Status**: Accepted
- **Date**: 2026-10-01
- **Deciders**: @jamaomonov
- **Tags**: process | backend | frontend | infra

## Context and problem statement

csmarket and YuPay are two products owned by the same person, in two repositories, with two
databases, two VPSes, two Waxpeer accounts and two sets of acquirer kassas. They share
**nothing at runtime** (spec §1, §2). YuPay, however, already contains most of what csmarket
needs, proven in production: the FastAPI kernel, Steam sign-in, Click / Payme / Uzum with
their webhook twins, the double-entry wallet, the CS2 skins catalogue and the Waxpeer client,
the Postgres-native queue, the infra and CI.

How should that code reach csmarket without dragging YuPay's other products (gift cards,
vouchers, suppliers, merchants, the Mini App) along with it?

## Decision drivers

- Speed: reuse what already works, including its tests.
- No leakage: no YuPay table, column, setting, route, name or dependency csmarket does not use.
- Independence: a YuPay change must never reach csmarket by accident, and vice versa.
- Reviewability: every ported line was chosen by someone, for a reason the plan states.

## Considered options

1. **Fork YuPay** and delete what csmarket does not need.
2. **Greenfield** — write csmarket from scratch, using YuPay only as reading.
3. **Port by allow-list** — a new repo; each milestone plan names the tables, functions and
   routes to bring over; they are copied, renamed and trimmed on the way in.

## Decision outcome

**Chosen option: 3, port by allow-list** (owner decision, spec §2 item 8), because it keeps
YuPay's proven code and tests while making every inclusion explicit.

The rules (spec §4, `AGENTS.md` § 6):

- **Allow-list.** A module is brought over by the list its milestone plan names; anything not
  on the list is not copied. Models are re-declared with only the columns spec §5 lists.
- **Rename on the way in.** `csmarket`, `csmarket_worker`, `csmarket_scheduler`,
  `@csmarket/*`, the `CSMARKET_` env prefix, cookie, metric, logger and Redis key names.
  `scripts/port-rename.sed` does the mechanical part; YuPay is never written to.
- **CI guard.** `scripts/check-no-yupay.sh` fails `lint-py` on YuPay-specific tokens in the
  source trees; legitimate exceptions (an acquirer's own field name, such as Click's
  `merchant_trans_id`) go in `scripts/check-no-yupay.allow` with a reason.
- **Tests and docs travel.** A ported module brings its YuPay tests, adapted, and a
  `README.md` describing what it owns here.

### Positive consequences

- Proven code and its regression tests arrive together, so a silent divergence fails CI.
- Nothing YuPay-specific leaks in; the guard makes the rule mechanical rather than a review
  habit.
- The two repos evolve independently — no shared library, no upstream to merge from.

### Negative consequences

- A slower start than a fork: every module is read, trimmed and re-tested by hand.
- A fix made in YuPay later does not reach csmarket by itself; porting it is a deliberate act.
- The forbidden-token list can collide with legitimate words (`merchant` in acquirer APIs),
  which costs an allow-list line each time.

### What was deliberately not ported in M0

- `core/outbound*` — YuPay's merchant-webhook delivery; csmarket has no merchants.
- `core/outbox` — in YuPay a small `Protocol` nothing implements: its fulfilment path moved to
  the Postgres-native queue instead (YuPay ADR-0064). csmarket's `orders` table **is** that
  queue (spec §5): a `paid` row is claimable with `FOR UPDATE SKIP LOCKED`, and the
  transaction that writes `paid` also sends `NOTIFY orders`. This departs from the spec §3.2
  `core` row, which listed `outbox`; everything else in that row is ported.

## Validation

- `scripts/check-no-yupay.sh` passes on every CI run.
- Each milestone's plan lists its allow-list, and its review checks the diff against it.
- Coverage of ported money modules stays at or above the gate in `AGENTS.md` § 9.

## Alternatives considered (detail)

### Option 1 — fork

Fastest first day. But the delete-what-you-don't-need pass never finishes: dead columns,
settings and code paths stay "just in case", and the history ties csmarket to YuPay's
decisions. Rejected by the owner.

### Option 2 — greenfield

Clean, but rewrites what already works — the wallet invariants, the acquirer protocols, the
Waxpeer edge cases measured in production — and loses their tests. Rejected by the owner.

## References

- Spec: `docs/superpowers/specs/2026-10-01-csmarket-design.md` §2, §3.2, §4, §5
- YuPay ADR-0064 (Postgres-native queue), in `~/Projects/yupay/docs/decisions/`
- `scripts/check-no-yupay.sh`, `scripts/check-no-yupay.allow`, `scripts/port-rename.sed`
