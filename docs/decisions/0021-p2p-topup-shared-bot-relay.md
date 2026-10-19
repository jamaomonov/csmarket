# 0021. P2P top-ups through a shared Telegram bot and a relay

- **Status**: Accepted
- **Date**: 2026-10-19
- **Deciders**: owner
- **Tags**: payments | infra

## Context and problem statement

The owner wants balance top-ups by a card-to-card transfer (spec
`2026-10-19-p2p-topup-design.md`), as YuPay already does: the owner's Humo card, @HUMOcardbot
notifications in the owner's Telegram, a Telegram Business bot reading that chat, a webhook,
an automatic match by card last4 + exact amount. The owner has one Telegram profile. A
Business account connects only **one** bot, and a bot has only **one** webhook URL — today
YuPay's.

## Decision drivers

- Both projects credit their own transfers automatically and independently of each other.
- No project holds the other's secrets; neither code base calls the other.
- A notification is never lost silently (Telegram keeps undelivered updates for 24 h).

## Considered options

1. **A relay** (Cloudflare Worker) that receives the webhook and forwards each update to both
   projects, answering Telegram 2xx only when both did.
2. **YuPay forwards** csmarket's updates — a change in YuPay, and csmarket's top-ups stop when
   YuPay is down.
3. **csmarket forwards** YuPay's — the same dependency, reversed.
4. **A second Telegram profile** with its own bot — the owner keeps one profile.

## Decision outcome

**Chosen option:** 1. `infra/p2p-relay` (~60 lines), deployed by the owner with wrangler;
three secrets (Telegram→relay, relay→YuPay, relay→csmarket). Each project matches only its own
cards: a credit whose last4 is no card of its own is journaled `ignored` (YuPay shipped the
same filter, `f7fddb57`). The two projects' cards must differ in their last four digits — the
owner checks a new card in each session.

Inside csmarket, P2P is a `p2p` gateway of the existing top-ups (top-ups only); the `p2p`
module holds the amount and settles through `payments.settle`. `payments` calls back into
`p2p` (`reserve_topup`, `details`) by a late import at request time — the one exception to
"`p2p` builds on `payments`", kept to two calls.

### Consequences

- One more piece of infrastructure (a free-tier Worker) on the path of every notification;
  its failure stops both projects' P2P (alert `P2PSilence`).
- `getWebhookInfo.pending_update_count` keeps its meaning ("not delivered to both").
- A Telegram reconnect of the bot resets its Business permissions for both projects.

## Validation

A 10 000 soʻm test top-up credited within seconds; YuPay's journal shows it `ignored`.
