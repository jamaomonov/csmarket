# referrals

Partners the admin picks earn a percentage of what the new accounts they bring buy, paid to
their site balance after an 8-day hold (spec `2026-10-27-referrals-design.md`, ADR-0026).

**Owns:** tables `referral_partners`, `referral_attributions`, `referral_rewards`,
`referral_visit_days` (migration `0043_referrals`).

- `referral_partners` — one per partner account: `code` (`^[a-z0-9-]{3,32}$`, unique),
  `percent` 0.1–20, `term_months` 1–120 or `NULL` = forever, `active`, the admin's `note`.
- `referral_attributions` — one per referred account (`user_id` PK): its partner and when.
- `referral_rewards` — one per delivered order of an attributed buyer (`order_id` PK):
  `base_uzs`, `percent`, `amount_uzs` (> 0), `status` `held` → `credited` | `cancelled`,
  `available_at = delivered_at + 8 days`.
- `referral_visit_days` — link visits per partner per UTC day.

**Interface (`api.py`):** the four models, `REF_COOKIE`, `credited_between`, `restart_after_unban` (analytics'
«Партнёрам»). `auth.service.steam_login` calls `attribution.attribute_new` for an account its
sign-in created on the storefront.

**Files:** `visits.py` (the link visit, its Redis dedup, `earning_partner`), `attribution.py`,
`partners.py` + `stats.py` + `admin_routes.py` (the admin), `me.py` + `routes.py` (the partner's
page, the visit), `rewards.py` (`accrue`, `hold_state`, `settle`; the scheduler job
`referrals.rewards` runs them hourly), `cursor.py`.

## Rules

- An account is tied only by the sign-in that created it, through the storefront, to an active,
  unbanned partner that is not itself. Never moved afterwards.
- A reward per delivered site order (`api_key_id IS NULL`) delivered at or after the
  attribution and before `attributed_at + term_months` (none for forever), from an active,
  unbanned partner; `floor(price_uzs × percent / 100) > 0`. `accrue` looks back 14 days.
- A delivery earns only from `active_since` on (set when the partner is created, switched back
  on, or its account unbanned — `admin.users_service.unban` calls `restart_after_unban`): the
  days it was off or banned never pay.
- After `available_at`: a rollback on the trade / purchase — the `rolled_back` attention now, or
  ever (`rolled_back_at`, stamped by `orders.trades.flag` and never cleared) — cancels; another
  open attention, a banned partner or a frozen wallet waits (`checked_at` is stamped, and the
  never-checked go first, so waiting rows never starve the rest); else credited, once per order.
- The `csm_ref` cookie is cleared only by a successful sign-in; a refused attempt keeps it.
- The partner never sees the buyer: its views carry amounts and dates only.

The ledger side is `wallet.credit_referral_reward` (kind `referral_reward`, D `user_wallet` /
C `house_referrals`, key `referral_reward:{order_id}`).
