# Referrals: partners earn from the buyers they bring

Agreed in conversation with the owner and approved on 2026-10-27.

## Why

Uzbek CS2 Telegram channels mostly refuse plain ads: many trade skins themselves or act as a
trade guarantor. A partner who earns a share of what their audience buys has a reason to post
about us. The first partners are channels, clubs and bloggers the owner talks to personally.

## Owner rulings

1. **Partners by invitation only.** An admin turns an existing account into a partner. There
   is no self-service sign-up.
2. **Reward = a percentage of the purchase amount**, set per partner. Not a share of profit.
3. **Attribution term per partner:** 6 months by default; any number of months, or «навсегда».
4. **The reward lands on the partner's site balance** (UZS) and is spent on skins. No card
   withdrawal.
5. **The referred buyer gets nothing.** No discount, no bonus.
6. **No QR code** for now — the link only.
7. **Analytics shows rewards as their own line «Партнёрам»** next to gross profit (by
   `credited_at`, credited rewards only); gross profit itself is unchanged.
8. **No per-order cap.** The admin form warns, when the percent is above 2 %: «На скинах от
   $1 000 маржа может уйти в минус.» Under the default pricing rules (2026-10-27) a 1 % reward
   leaves 5–9 % of the price on skins up to ~$300 and 3–4 % on $1 500+ (3 % expenses counted
   as ours); the 30 days on prod averaged 10.7 % gross margin, 9.7 % after 1 %.
9. **No alt-account guard.** Partners are hand-picked; the runbook names the risk (a partner's
   second account buying through its own link, cashing out via the buy-back) and how to spot it.

## Calls I made (the owner may overrule)

- **Only new accounts are attributed.** An account is tied to a partner at its first Steam
  sign-in, never later. Existing customers cannot be "taken" by a link.
- **The partner code** is set by the admin: lowercase latin, digits and `-`, 3–32 chars,
  unique (`zufarmax`). Link: `https://csmarket.uz/?ref=<code>`; `ref` works on any storefront
  page and any locale.
- **The link is remembered 30 days**, last click wins (a later link from another partner
  replaces the earlier one before the account exists).
- **Only delivered market orders earn.** Status `delivered`. Not buy-back (sales), not public API
  orders (`api_key_id` set), not top-ups. `failed` / `returned` / `cancelled` earn nothing.
- **The base is `orders.price_uzs`** — what the buyer paid. Reward = `floor(price_uzs × percent / 100)`,
  whole soʻm; a reward of 0 is not booked.
- **The term is counted from the account's attribution moment** (its first sign-in). An order earns
  if its `delivered_at` falls inside the term.
- **8-day hold.** Steam lets a trade be reversed within 7 days (trade protection). A reward
  becomes available 8 days after `delivered_at`. `delivered` is terminal (no refund leaves it);
  a reversal shows as the `rolled_back` attention on the order's trade / purchase row
  (`skin_trades`, `skinslink_purchases`, `lisskins_purchases`), including a Skinslink
  `reverted` that arrives delivered and rolled back at once. When the hold ends:
  - any `rolled_back` ever opened on the order (resolved or not) → the reward is `cancelled`
    (`rolled_back`). A resolution does not record whether the skin stayed; if it did, the
    admin credits the partner by hand (a balance adjustment);
  - another unresolved attention (`ambiguous_trade`, `audit_divergence`, …) → the reward stays
    `held` and is credited once the attention is resolved;
  - otherwise it is credited and final. A later rollback is the admin's call (a manual
    adjustment).
- **A frozen partner wallet** (the ledger refuses a posting) keeps the reward `held`; the job
  retries each run, as sales' `credit_blocked` does. A banned partner (`users.banned_at`) earns
  nothing new, like an inactive one; rewards already held wait the same way.
- **`users.upsert_user_by_steam` must report whether it created the account**, so sign-in
  can write the attribution only for a new one.
- **Percent and term changes apply to orders delivered after the change.** A reward is fixed
  (amount and percent stored) when its order is delivered.
- **A partner switched off** keeps rewards already in the hold (they still credit), earns
  nothing on new deliveries, and its link stops attributing new accounts. Accounts already
  tied stay tied (switching it back on resumes earning within their term).
- **A partner's own account is never attributed to itself** (it is not new anyway, but the
  rule is explicit).
- **Percent bounds:** 0.1–20 %, one decimal place. Term: 1–120 months or `null` = forever.

## Data (`modules/referrals`)

- `referral_partners`: `user_id` (PK, the partner's account), `code` (unique), `percent`
  (numeric(4,1)), `term_months` (int, null = forever), `active` (bool), `note` (admin text),
  `created_at`, `updated_at`.
- `referral_attributions`: `user_id` (PK, the referred account), `partner_id`, `attributed_at`.
- `referral_rewards`: `order_id` (PK), `partner_id`, `referred_user_id`, `base_uzs`, `percent`,
  `amount_uzs`, `status` `held` → `credited` | `cancelled`, `available_at`
  (`delivered_at + 8 days`), `credited_at`, `cancelled_reason`, `created_at`.
- `referral_clicks` or a daily counter: per partner per day, the number of link visits. Visits are
  deduped per visitor per day the way article views are (a salted hash in Redis, no IP stored).

Wallet: a new transaction kind `referral_reward`, D `user_wallet` / C `house_referrals` (a new
house account), key `referral_reward:{order_id}`. Booked through a `wallet` function the way
`credit_sale` is.

## Flow

1. A visitor opens a link with `?ref=zufarmax`. The storefront calls the API
   (`POST /referrals/visit {code}`), which counts the visit and sets an HttpOnly cookie
   `csm_ref` (30 days, host-only on the API host like `csm_aid`; the sign-in call goes there) when the code belongs
   to an active partner. An unknown or inactive code does nothing and says nothing. The storefront
   drops `ref` from the URL (replace, no reload) so it is not shared further or indexed.
2. On `POST /auth/steam`, when the account is created in this request and `csm_ref` names an
   active partner, an attribution row is written in the same transaction. The cookie is cleared
   on every sign-in.
3. An hourly job finds orders that became `delivered` (last 14 days) whose buyer has an
   attribution with an active partner and whose delivery falls in the term, and writes a `held`
   reward row for each (one per order). `orders` is not touched: four code paths deliver an
   order, and a pull keeps `orders` unaware of `referrals` (ADR-0026). The percent is read then,
   at most an hour after delivery.
4. A scheduler job (hourly) takes `held` rewards whose `available_at` has passed and applies
   the hold rules above: cancel on any `rolled_back`, wait on another unresolved attention or a
   frozen wallet, otherwise book the wallet transaction and mark `credited`. Idempotent by the
   wallet key.
5. Analytics: a «Партнёрам» line — the sum of rewards credited in the window (by
   `credited_at`), beside gross profit.

## Partner page (storefront, `/account/referral`)

The existing «Реферал» page (today «Скоро») becomes the partner page. A partner is an account
with the `partner` role (added when the admin creates the partner). A non-partner who opens the
URL sees a short «Программа по приглашению» note; the «Скоро» teaser on the profile goes. In ru / uz / en:

- the link with a copy button;
- the terms: percent and term («6 месяцев» / «навсегда»);
- counts for this month and all time: visits, new accounts, purchases, earned;
- money: «В ожидании» (held, with the nearest date) and «Начислено» (credited);
- a list of rewards, newest first: date, order amount, reward, status. **No buyer identity**
  (no name, no Steam ID, no order number — the partner sees amounts and dates only).

A link to it in the account menu, only for partners.

## Admin («Партнёры»)

- The list: account, code, percent, term, active, new accounts, delivered orders, revenue
  brought, rewards held / credited. Sort by revenue.
- Create: «Сделать партнёром» on the user's card in «Пользователи» (find the account there as
  usual), set code, percent, term, note.
- Edit: percent, term, active, note. The code cannot change once there is an attribution (old
  links would break); before that it can.
- A partner's page: its stats by month and its rewards with the order numbers (admins see
  orders).
- Every write is audited (`referrals.partner.create` / `update`) and keyed.
- The user's page in the admin shows «Привёл: <partner>» when the account is attributed.

## Not now

- Self-service partner sign-up; a QR code; a discount for the referred buyer.
- Rewards on buy-back (sales).
- Card withdrawal of the reward.
- Attributing an existing account by an admin by hand.

## Docs

ADR (the reward as a ledger kind; attribution at account creation only), module README,
`module-map.md`, `cache-keys.md` (visit dedup keys), `pii-handling.md` (attribution links two
accounts; the partner never sees the buyer), `docs/api/README.md`, a runbook
`referrals.md` (adding a partner, a rollback after credit), the coverage gate for the new module.
