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

**Interface (`api.py`):** the four models.

The ledger side is `wallet.credit_referral_reward` (kind `referral_reward`, D `user_wallet` /
C `house_referrals`, key `referral_reward:{order_id}`).
