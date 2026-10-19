# P2P top-ups — runbook

A buyer tops up the balance by a card-to-card transfer to the owner's Humo card. @HUMOcardbot
notifies the owner's Telegram; the shared Telegram Business bot reads only that chat; its
webhook goes to the **relay** (`infra/p2p-relay`), which forwards every update to YuPay and to
csmarket; csmarket matches a credit by **card last4 + exact whole amount** to an open request
and settles the top-up. Spec `docs/superpowers/specs/2026-10-19-p2p-topup-design.md`,
ADR-0021.

## 1. One-time setup (with the YuPay session)

The bot is the one YuPay already uses; do not reconnect it casually (a reconnect resets its
chatbot permissions).

1. BotFather: **Business Mode** on and **Bot-to-Bot Communication Mode** on (HUMO is a bot;
   without it, its messages never reach a business bot).
2. Telegram → Settings → Business → Chatbots: the bot, **«Only selected chats: HUMO Card»**,
   and the **Messages** permission on (with only "gifts and stars" nothing arrives).
3. The csmarket card's last four digits must differ from every YuPay card: say them in the
   YuPay session and let it check (YuPay never shares its last4s). Never add the csmarket card
   to YuPay.
4. Secrets: `CSMARKET_P2P_WEBHOOK_SECRET` in `secrets/api.env` on the server (a long random
   string, `scripts/gen-secret.sh`); the same value goes into the relay as `CSMARKET_SECRET`.
5. Deploy the relay (`infra/p2p-relay/README.md`), then `setWebhook` to it with the relay's
   own secret and `allowed_updates=["business_message","business_connection"]`.
6. Admin → **P2P → Настройки**: the HUMO bot's numeric id (`business_message.from.id` from one
   `getUpdates` before `setWebhook`, or from the YuPay session) and the owner's own Telegram
   id. Then toggle the bot's Business connection off and on once: the intake pins the
   owner's connection from that update (Настройки shows «подключено»).
7. Admin → **P2P → Карты**: add the card (the full number once; it is stored sealed and shown
   masked). Set min / max / the daily limit.
8. Admin → **Настройки → Оплата**: «Перевод на карту (P2P)» → «Работает». Make a 10 000 soʻm
   test top-up from a second account.

Go-live order: YuPay deploys its foreign-card filter → csmarket deploys (P2P off) → the relay →
(the old spike token revoked, a new one in YuPay's sops, if it never was) → `setWebhook` to
the relay → card → switch on.

## 2. How a request works

- A request holds an exact amount on a card for **10 minutes** (the typed amount, or up to
  +99 soʻm when that amount is open on the card). The top-up takes the held amount.
- After a request closes (paid or expired) its amount stays **quarantined 10 minutes**: a late
  delivery of an on-time transfer still pays it; a repeated transfer lands unmatched and
  never pays the next buyer of the same amount.
- `p2p.sweep` (scheduler, every 30 s) expires requests and releases quarantine; an unpaid
  request's top-up then expires.
- Limits (Admin → P2P → Настройки): one top-up 10 000 – 5 000 000; per buyer per Tashkent day
  ≤ 3 requests and ≤ 10 000 000; one open request at a time; the card's own daily limit.

## 3. Manual credit of an unmatched transfer

Journal (Admin → P2P → Журнал) rows `unmatched` are money nobody was waiting for: a wrong
amount, a transfer after the window, or two active cards with one last4.

1. Find the buyer (the receipt the buyer sent to support, the amount and the time).
2. Do **not** credit while a request of that card and amount is pending or quarantined — the
   button refuses (`p2p_quarantine`); wait out the 10 minutes.
3. «Зачислить пользователю» → the buyer → confirm. The row turns `matched`; a second credit of
   the same row is refused (`p2p_already_credited`). Audited `p2p.incoming.credit`.

Money back to the payer's card is a manual bank transfer, then «Изменить баланс» on the user
card to take it off the balance.

## 4. Alerts

### unparsed

`P2PUnparsed`: a HUMO message the parser could not read; nothing in it was credited. Open the
journal row (`kind = unparsed`). One odd message: credit by hand (§3) if it was a credit. Every
message failing: HUMO changed its format — switch P2P to «Тех. работы», fix `p2p/parsing.py`
with the new sample in its tests, deploy, switch back.

### chain-break

`P2PChainBreak`: the card's balance did not follow from the previous message — a notification
was missed or arrived out of order. Compare the journal with the bank's statement; a missing
credit is credited by hand (§3). Telegram keeps undelivered updates for 24 h only.

### ambiguous-card

`P2PAmbiguousCard`: two **active** cards end in the same four digits; nothing to them is
credited automatically. Deactivate one; credit the stuck transfers by hand.

### settle-refused

`P2PSettleRefused`: a transfer matched a request, but its top-up had already been settled
another way (paid through a kassa meanwhile). The transfer is on the journal as `unmatched`:
credit it by hand to that buyer (§3) after checking their balance history, or return it.

### inactive card

A card switched off while a request on it is open: the buyer's on-time transfer lands
`unmatched` (only active cards match). Wait for open requests to close before switching a card
off, or credit such transfers by hand.

### silence

`P2PSilence`: requests expire and no HUMO message arrived for an hour. Check in order:
`getWebhookInfo` (last error, `pending_update_count`), the relay's logs and the queue
`csmarket-p2p` / its dead-letter queue (Cloudflare), the
Business connection in Telegram (still on, «HUMO Card» selected, Messages on), Admin → P2P →
Настройки («последнее уведомление»). Meanwhile switch P2P to «Тех. работы».

## 5. Switches

Admin → Настройки → Оплата → P2P: «Работает» / «Тех. работы» (the tile is greyed, no new
requests) / «Выключен» (no tile). Open requests settle in every state.
