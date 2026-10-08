# Selling skins to us (Skinslink deposits) — design

- **Status:** draft for the owner's review (2026-10-08). Every decision below was taken with the
  owner in conversation on 2026-10-08.
- **Why:** the buy side works on three sources. The sell side ("выкуп") is the next revenue
  line. Skinslink takes the user's skins through its deposit API and credits **our** merchant
  balance in USD. We pay the user in soʻm, minus our margin.
- **API** (`https://api.skinslink.com/api/v1`, `X-Api-Key`, our VPS IP whitelisted):
  - `POST /merchant/inventory {game, partner, token}` returns `{items[{id, name, price,
image_url, exterior, rarity, rarity_color}], total, sum, max_items}`. The prices are a
    5-minute snapshot.
  - `POST /merchant/create-deposit {merchant_tx_id, game, partner, token, asset_ids,
min_prices?}` returns `{id, status, amount, bot_name, trade_offer_id,
trade_offer_expiry_at}`.
  - `GET /merchant/deposit/status?merchant_tx_id=` returns `{status, fail_reason,
hold_end_date, …}`.
  - The deposit webhook sends `{sign, status, trade_id, merchant_tx_id, amount, hold_end_date?,
fail_reason?}`, signed `base64(sha256(str(trade_id) + secret))`.
  - Statuses: `new → pending → active → hold → completed`, with `failed`, `canceled` and
    `reverted` (only out of `hold`). Webhooks come only for `hold`, `completed`, `failed`,
    `canceled` and `reverted`.
- **Not in this version:**
  - KYC and an instant credit up to ~300 $ before the hold ends (later);
  - automatic card payouts (admins pay by hand);
  - `deposit-preview` / `from_preview` (wired behind a flag once Skinslink enables it on our
    account);
  - games other than CS2.

## 1. Goal and success

- A signed-in user with a trade link sees their tradable CS2 inventory priced in soʻm, picks
  items, chooses where the money goes and gets one Steam trade offer from a Skinslink bot.
- The money becomes theirs only when the trade has cleared Steam's 7-day protection
  (`completed`):
  - on the csmarket balance, as a ledger credit;
  - on a card, as a payout request an admin pays by hand and marks paid.
- Our margin is configurable by price bracket. The card fees, the balance bonus and the
  minimums are configurable in the admin, per card type.
- No path pays a user twice, pays for a reverted trade, or pays without a verified
  `completed`.

## 2. Constraints carried in

- Money rules from AGENTS.md:
  - `Decimal` throughout; USD to 6 places, soʻm in whole units;
  - every state-changing endpoint takes an `Idempotency-Key`;
  - no PII in logs.
- The card number is PII and sensitive:
  - encrypted at rest (`core/crypto`);
  - logs, metrics and lists show the last 4 digits only;
  - the full number is shown to an admin in the request's page, and showing or copying it is
    audited.
- No external call holds a DB lock or an open transaction (as in the buy paths).
- **Kill switches:** the `CSMARKET_SALES_ENABLED` env flag (default `false`) and the admin's
  «Выкуп включён» switch. Both must be on.

## 3. Pricing

**Price per item, in soʻm:**

```
units      = Skinslink price (USD)
margin     = progressive bracket margin on units (sale_settings.margin, like the retail
             brackets, e.g. 0–1 $ 10 %, 1–10 $ 5 %, 10–100 $ 3 %, 100+ $ 2 %)
ours_usd   = units − margin
rate       = CBU rate × (1 − rate_cut_pct / 100)      # the 1 % sell uplift is NOT applied
price_uzs  = floor(ours_usd × rate / 100) × 100       # rounded down to 100 soʻm
```

**Rules on the whole sale:**

- **The minimum is on the sum, not on each item:** the sum of the chosen items' Skinslink prices
  must be ≥ 1 $ (Skinslink's own minimum). Ten items at 0.10 $ are accepted; one is not.
- **Payout to the balance:** `Σ price_uzs × (1 + balance_bonus_pct / 100)`, rounded down to 100.
- **Payout to a card:** `Σ price_uzs × (1 − card_fee_pct[card type] / 100)`, rounded down to 100. It must be ≥ `card_min_uzs` (default 30 000).
- **The payout is fixed when the sale is created.** It is what the user saw.
- **Price drift:** `min_prices` = each item's Skinslink price × 0.99. If Skinslink credits less
  than quoted, it is never below that floor, and we absorb the gap.

## 4. Data

| Table             | What it holds                                                                                                                                                                                                                                                                                                                                                         |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sales`           | One per deposit: `id` (the `merchant_tx_id`), `number`, `user_id`, `status`, `payout_to` (`balance`/`card`), `payout_card_id`, `quoted_usd` (Skinslink sum), `amount_usd` (credited), `payout_uzs`, `rate`, `margin_usd`, Skinslink `trade_id`, `trade_offer_id`, bot, `offer_expiry_at`, `hold_end_at`, `fail_reason`, `credited_at`, `attention_reason`, timestamps |
| `sale_items`      | `sale_id`, `asset_id`, `name`, `image_url`, `price_usd` (Skinslink), `price_uzs` (ours)                                                                                                                                                                                                                                                                               |
| `payout_cards`    | `user_id`, `type` (`uzcard`/`humo`/`uzum_visa`), `number_enc`, `last4`, `deleted_at`. At most 3 live per user                                                                                                                                                                                                                                                         |
| `payout_requests` | `sale_id`, `user_id`, `card_id`, `amount_uzs`, `fee_uzs`, `status` (`waiting_hold`/`to_pay`/`paid`/`rejected`/`canceled`), `paid_by`, `paid_at`, `note`, `reject_reason`                                                                                                                                                                                              |
| `sale_settings`   | One JSON document (`id = 1`), like `skin_pricing_rules`: `enabled`, `margin[]`, `rate_cut_pct`, `balance_bonus_pct`, `card_fee_pct{uzcard, humo, uzum_visa}`, `card_min_uzs`, `min_sum_usd` (1)                                                                                                                                                                       |

**Sale statuses:**

| Status     | Meaning                                              |
| ---------- | ---------------------------------------------------- |
| `creating` | The request went out; the answer is not recorded yet |
| `offered`  | Skinslink `active`: the bot's offer is out           |
| `hold`     | Skinslink `hold`                                     |
| `credited` | `completed` + balance                                |
| `payout`   | `completed` + card: the request is `to_pay`          |
| `closed`   | `failed` or `canceled`                               |
| `reverted` | Rolled back out of `hold`                            |

**Wallet:**

- a new house account kind `house_skin_buys`;
- a credit is `debit house_skin_buys / credit user_wallet`, keyed by the sale id, so it can
  happen only once;
- a rejected card payout credits the balance the same way, keyed by the request id.

The balance page shows "ожидает зачисления" as `Σ payout_uzs` of the user's `hold` sales with
`payout_to = balance`. No ledger posting is made before `completed`.

## 5. API (storefront)

- `GET /sell/inventory` returns the priced inventory: our prices and Skinslink's `max_items`.
  Skinslink lists only the items it accepts and that are tradable now. Items it does not take
  (and trade-locked ones) are simply absent, so the demo's «Не принимаем» / «Обмен с …» plaques
  go.
  - Needs sign-in and a trade link.
  - Cached 5 minutes per user. `?refresh=1` refetches.
  - Has its own `ip_guard` bucket.
  - **External call:** Skinslink `inventory`, with a 6 s timeout and a breaker. It is a new
    AGENTS §11 carve-out (advisory, no DB session held across it).
- `POST /sell {asset_ids, payout: {to: "balance"} | {to: "card", card_id} | {to: "card",
new_card: {type, number}}}` with an `Idempotency-Key`. It:
  1. re-prices from the cached snapshot;
  2. checks the minimums, `max_items` and the kill switches;
  3. stores the sale (`creating`) and its items, and the card if new (Luhn and prefix
     checked);
  4. commits;
  5. calls `create-deposit`;
  6. records the offer (`offered`).

  It answers the sale. It is a new AGENTS §11 carve-out: one external call, no open
  transaction across it.

- `GET /sales`, `GET /sales/{number}` — the user's sales.
- `GET /payout-cards`, `DELETE /payout-cards/{id}`.
- WebSocket nudge `sale.updated`, as orders have.

## 6. Status flow

- **The webhook** (`/skinslink/webhook`, already exempt from the coarse rate limit) verifies
  `sign` before reading anything else. It then enqueues a check of `merchant_tx_id` and answers 200. The check always asks `deposit/status` and acts on that answer, never on the webhook's
  amounts.
- **Polling:**
  - every 60 s for `creating` and `offered` sales (no webhooks before `hold`);
  - every 30 min for `hold` sales, in case a webhook was lost.
- **Transitions:**
  - `creating` + not found, past a 2-minute grace → `closed` (the call never landed).
  - `creating` / `offered` + `active` → `offered`.
  - `hold` → `hold`, storing `hold_end_at`. A card sale's request becomes `waiting_hold`.
  - `completed`:
    - balance → credit (+bonus) → `credited`;
    - card → the request goes `to_pay` → `payout`.

    The credit is idempotent per sale.

  - `failed` / `canceled` → `closed`, storing `fail_reason`. A request, if any, → `canceled`.
  - `reverted` → `reverted`. A request, if any, → `canceled`. Nothing was paid.
  - `reverted` after we credited (not expected per the docs) → `attention_reason =
rolled_back`. No automatic debit.
- **`create-deposit` errors:**
  - `inventory_reload` or `item_specified_price_not_found` → 409 `prices_changed`, the
    storefront reloads;
  - `409 already exist` → adopt, through `deposit/status`;
  - Steam account errors → 409 with the code mapped to a Russian message;
  - a timeout or a 5xx → stays `creating`, and polling settles it.

## 7. Admin

- **«Выкуп» → «Заявки на выплату»:**
  - status tabs with counts; «К выплате» is the default;
  - a row shows the sale number, the user, the masked card, the amount and since when it is
    payable;
  - the request page shows the full card number with «Скопировать» (audited), the amount
    breakdown, the items, and the user's sales and payouts history;
  - «Выплачено» (with an optional note) and «Отклонить» (a reason is required: the amount
    without the card fee is credited to the balance) are admin-only and audited;
  - the dashboard gets a «К выплате» tile;
  - an alert fires when a request has been `to_pay` for more than 48 h.
- **«Продажи»:** a list and a page per sale: statuses, the Skinslink amount, our payout and our
  margin.
- **«Настройки выкупа»:** the `sale_settings` editor. A save affects new sales only and is
  audited.

## 8. Storefront

- **`/sell`:** the demo, made real. It has the states signed out / no trade link / inventory.
  - Only the items Skinslink accepts are shown. A line under the grid says «Показаны предметы,
    которые можно продать сейчас».
  - The cart holds the payout choice (balance with its bonus, saved cards, a new card), the
    summary and «Продать за {sum}».
  - «Продать» stays disabled under the minimum, with «Добавьте ещё на {sum}».
- **`/account/sales/{number}`:** «Примите обмен» (the offer link, the bot, accept by), then
  live statuses.
- **Account:**
  - «Продажи» — the user's sales;
  - «Мои карты» — the saved cards;
  - the balance shows «Ожидает зачисления».
- **Copy:** ru / uz / en, no supplier names, no "hold" or "deposit".
- **Emails:** hold, credited / paid out, cancelled.

## 9. Testing

- **Contract tests** (`respx`) for `inventory`, `create-deposit`, `deposit/status` and every
  error in §6.
- **Integration tests:** the full flow per terminal status; webhook signature; idempotent credit
  and a replayed webhook; polling of `creating`; price drift; the minimums; card validation;
  request paid / rejected → balance; the kill switches.
- **Coverage:** the `sales` module is added to the 95 % gate.
- **TypeScript:** `/sell`, the sale page, the cards, and the admin's requests, sales and
  settings.

## 10. Documents and rollout

- **Documents:**
  - ADR-0016 «Selling skins through Skinslink deposits»;
  - `modules/sales/README.md`;
  - the module map;
  - `docs/architecture/sequence-diagrams/skin-sale.mmd`;
  - `docs/runbooks/sales.md` (paying requests, rejections, stuck sales);
  - `pii-handling.md` (cards);
  - `cache-keys.md`, `metrics.md`;
  - API notes;
  - AGENTS §11 carve-outs.
- **Rollout:**
  1. deploy with `CSMARKET_SALES_ENABLED=false`;
  2. set the Skinslink merchant webhook URL (the same endpoint);
  3. a test sale by the owner;
  4. turn it on.
