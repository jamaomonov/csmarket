# P2P balance top-up and kassa switches

Approved in conversation with the owner on 2026-10-19. Ported by allow-list from YuPay's P2P
deposit (YuPay ADR-0094 / ADR-0097, spec `2026-10-04-p2p-deposit-design.md`, runbook
`p2p-deposit.md`), cut down to balance top-ups. Coordinated with the YuPay session, which
shipped its side (foreign-card filter, runbook) locally as `f7fddb57`.

## Goal

1. A buyer tops up the balance by a card-to-card transfer to the owner's Humo card: no kassa,
   no fee, credited automatically within seconds of the bank's notification.
2. Every kassa (Click, Payme, Uzum, P2P) gets a switch: on, maintenance (the tile stays,
   greyed and not clickable, «Технические работы»), off (no tile). Enforced on the server.

## Owner rulings

1. **Top-ups only.** P2P never pays an order directly (for now).
2. **The mechanism is YuPay's:** the owner's Humo card; @HUMOcardbot notifies the owner's
   Telegram profile; a Telegram Business bot reads only that chat; the update reaches us by
   webhook; the parsed credit is matched by **card last4 + exact whole-soʻm amount** to an
   open request. No admin confirms a matched transfer.
3. **Same Telegram profile and the same bot as YuPay, a different card.** A Business account
   connects one bot and a bot has one webhook, so the webhook goes to a **relay** that
   forwards every update to both projects (below).
4. **Basic limits only** (no new-account rules, no hold on selling P2P money): one top-up
   10 000 – 5 000 000 soʻm; per user per day at most 3 P2P top-ups and 10 000 000 soʻm; a
   daily limit per card; one open request per user. All editable in the admin.
5. **Kassa switches** apply to Click, Payme, Uzum and P2P, for orders and top-ups alike.
6. Support for a late transfer: the owner's Telegram (`@jama_omonov`), with the receipt and
   the request number.

## Storefront

**Top-up page → «Перевод на карту»** beside the kassas (P2P is not offered at checkout).

1. The buyer types an amount (the limits above; the page says the range).
2. `POST /wallet/topups {provider: "p2p"}` opens the top-up and a **reservation**. The page
   shows: the card number grouped by four with «Скопировать», the holder's name, the **exact
   amount** (the typed amount, or up to +99 soʻm when that amount is already open on the
   card) with «Скопировать», a 10-minute countdown, and «Переведите ровно … — иначе платёж
   не найдётся».
3. The page polls the top-up every 3 s; on `succeeded` it shows «Зачислено» and the new
   balance.
4. On expiry: «Время вышло» with «Новая заявка», and «Уже перевели? Напишите в поддержку с
   чеком и номером заявки» (the Telegram link).

Copy in ru / uz / en. The card number appears only to a signed-in buyer who opened a request.

## Kassa switches

`payment_settings` (row 1, the kassa-fee document) gains `status` per kassa:
`on | maintenance | off`, default `on`; P2P defaults to `off` until the owner turns it on.

- `GET /payments/providers` lists `on` and `maintenance` kassas (each with `status`), never
  `off` ones. The storefront draws a `maintenance` tile greyed, not clickable, with
  «Технические работы».
- Opening an order payment or a top-up in a `maintenance` / `off` kassa is **409**
  `provider_maintenance` / `provider_disabled` (checked in `create_topup` and the order's
  pay path). The storefront says so and offers another kassa.
- Payments already opened finish: webhooks and the P2P intake keep settling them in any
  status (otherwise a buyer could be charged and not credited).
- Admin «Настройки → Оплата»: a three-way switch beside each kassa's fee; the save is audited
  with the fees (`payments.settings.save`).

## Backend — module `p2p`

Tables (one migration):

- `p2p_cards` — PAN sealed with `core.crypto` (ciphertext + nonce), `pan_last4`, holder,
  network (`humo` / `uzcard`), `active`, `min_uzs`, `max_uzs`, `daily_limit_uzs` (nullable),
  timestamps. Adding a card whose last4 equals another **of ours** is refused
  (`p2p_last4_taken`); the owner checks a new card's last4 against YuPay's in the YuPay
  session (YuPay refuses to share its last4s).
- `p2p_reservations` — `number` (the top-up's), `topup_id`, `payment_id`, `card_id`,
  `amount_uzs`, `status` `pending → paid | expired | cancelled`, `expires_at`,
  `holds_amount`, `quarantine_until`, `paid_at`, `incoming_id`. Partial unique
  `(card_id, amount_uzs) WHERE holds_amount`; one `pending` per user.
- `p2p_incoming` — every notification: `business_connection_id`, `telegram_message_id`
  (unique together), `kind` credit / debit / unparsed, `amount_uzs`, `card_last4`,
  `bank_time`, `balance_after`, `chain_ok`, `raw_text`, `result`
  matched / unmatched / ignored, `reservation_id`, `received_at`.
- `p2p_settings` (row 1) — `humo_bot_id`, `owner_telegram_user_id`, the pinned
  `business_connection_id`, the limits of ruling 4.

Logic (ported from YuPay's `parsing.py`, `card_choice.py`, `reservations.py`, `intake.py`,
the sweep):

- **Reserve:** the user's limits (count and soʻm today in Tashkent, one pending) → a card
  whose min/max fit and with the most daily room (per-card advisory lock) → the first free
  amount from `amount` to `amount + 99` on it → else the next card → else 409
  `p2p_unavailable`. A reservation lives 10 minutes; once closed, its amount stays
  **quarantined 10 minutes**.
- **Intake** `POST /api/v1/webhooks/telegram/p2p`: the `X-Telegram-Bot-Api-Secret-Token` is
  compared with `CSMARKET_P2P_WEBHOOK_SECRET` (`hmac.compare_digest`) **before** the body is
  parsed; only `business_message` from the pinned connection whose sender and chat are the
  HUMO bot, not forwarded; edits ignored. Journal first (a duplicate message id is a no-op),
  then: a credit whose last4 matches **no card of ours** → `ignored` (YuPay's card); two
  active cards with that last4 → `unmatched` + alert; else match last4 + exact amount + a
  pending (or quarantined-expired) reservation created before the bank time → `paid`, and
  the top-up's payment is settled through `payments.hooks.settle` (the same booking as
  Click / Payme, keyed `p2p:<incoming id>`). Everything in one transaction; the webhook
  answers 200 after commit. On the exempt list of `bootstrap._exempt_self_authenticating_routes`.
- **Sweep** (scheduler, every 30 s): expire pending reservations past `expires_at` (their
  top-ups expire), release quarantine.
- **Manual credit** of an unmatched transfer (admin): only once no reservation of that card
  and amount is pending or quarantined; settles the chosen user's new top-up with the
  incoming row attached; audited `p2p.incoming.credit`. Never a second time for one row.

Alerts (Prometheus counters → Alertmanager → Telegram, runbook `docs/runbooks/p2p.md`):
`P2PUnparsed` (an unparsed notification), `P2PChainBreak`, `P2PSilence` (a reservation
expired while no notification arrived for 60 min), `P2PAmbiguousCard`.

## The relay

`infra/p2p-relay/` — a Cloudflare Worker (~60 lines) the owner deploys with `wrangler`:

- Telegram calls it with the relay's own secret (`setWebhook … secret_token`,
  `allowed_updates=["business_message","business_connection"]`).
- It forwards the body unchanged to YuPay (header = YuPay's `P2P_WEBHOOK_SECRET`)
  synchronously and answers Telegram 2xx exactly when YuPay did (502 otherwise, Telegram
  retries); csmarket's copy (header = csmarket's secret) goes through a Cloudflare Queue with
  retries, so csmarket being down never stops YuPay (agreed with the YuPay session).
- Three secrets, held by the Worker; csmarket never holds YuPay's and vice versa.

Go-live order (with the YuPay session): YuPay deploys its foreign-card filter → csmarket
deploys P2P (switch `off`) → the relay is deployed → (the old spike token is revoked if it
never was) → `setWebhook` to the relay → the owner adds the csmarket card in the admin and
turns P2P on.

## Admin «P2P»

- **Карты** — add (full number typed once, then masked), enable / disable, min / max / daily
  limit, today's received sum.
- **Журнал** — incoming notifications newest first, search by amount, result chips; an
  unmatched credit offers «Зачислить пользователю» (rules above).
- **Заявки** — reservations with status chips, the user, the card, the amount, the time left.
- **Настройки** — the limits, the HUMO bot id, the owner's Telegram id, the pinned
  connection's state, the last notification's time.

## Security and PII

The card PAN is sealed at rest and shown only masked in the admin and in full only to the
buyer of an open request. `raw_text` of a notification holds amounts and the masked card,
no payer data; never logged. The webhook is authenticated before parsing; its secret lives
in `secrets/api.env`. Update `docs/security/pii-handling.md`.

## Testing

Unit: the HUMO parser (credit, debit, unparsed, odd spacing), the amount bump and card
choice. Integration: reserve with limits (count, sum, one pending, min / max, card daily
limit, the +99 bump, no card → 409); intake (bad secret before parse, foreign last4 ignored,
duplicate message no-op, exact match credits once, a late transfer within quarantine still
pays its reservation, after quarantine unmatched, amounts with tiyin never match, ambiguous
last4); sweep; manual credit refused while quarantined, done once; kassa switches (maintenance
listed with status, off hidden, both 409 for new payments, an open payment still settles).
Admin and storefront: Vitest for the top-up screen, the maintenance tile, the P2P pages.
The relay: a Worker unit test with both targets mocked (2xx on YuPay's 2xx; csmarket queued and retried).

## Docs

This spec; an ADR (P2P top-up through a shared bot and a relay); `modules/p2p/README.md`;
`docs/runbooks/p2p.md` (BotFather modes, Business chatbot access «Only selected chats: HUMO
Card», Messages permission, the relay, setWebhook, the manual-credit rule, alerts);
module map, cache keys if any, metrics, `make gen-api`.

## Out of scope

Paying an order by P2P. Refunds to a card through the system. Uzcard notifications (only
the HUMO bot format). New-account limits and holds on P2P money (owner: basic limits only).
