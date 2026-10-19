# p2p

Balance top-ups by a card-to-card transfer (spec `docs/superpowers/specs/2026-10-19-p2p-topup-design.md`,
ADR-0021, runbook `docs/runbooks/p2p.md`). Top-ups only: P2P never pays an order.

**Owns:** `p2p_cards` (the number sealed with `core.crypto`), `p2p_reservations` (one open
amount per card, one pending request per buyer), `p2p_incoming` (every HUMO notification,
deduped by Telegram message), `p2p_settings` (row 1: trusted Telegram ids, the buyer's limits).

**Depends on:** `payments.api` (the top-up's attempt: `mark_pending`, `settle`,
`cancel_pending`, `credit_received_transfer`), `orders.api` (`TASHKENT`), `admin.api`, `users.api`.
`payments` calls back `reserve_topup` / `details` by a late import (ADR-0021).

## Flow

1. `POST /wallet/topups {provider: "p2p"}` → `payments.create_topup` → `reserve_topup`: the
   buyer's limits, a card (`card_choice`: min/max, most daily room, advisory lock), the first
   free amount `amount … amount+99` (the partial unique index decides races). The top-up takes
   the held amount; its attempt is held (`pending`) so no top-up expiry touches it.
2. The buyer transfers. HUMO notifies; the relay posts the update to
   `POST /webhooks/telegram/p2p` (`routes.py`: the secret before the body).
3. `intake.ingest_update`: only the HUMO bot's unforwarded messages through the pinned
   connection; journal; a foreign last4 → `ignored`; two active cards with one last4 →
   `unmatched` + alert; else last4 + exact whole amount + a pending (or quarantined-expired)
   request created before the bank time → `paid`, the top-up settled once.
4. `p2p.sweep` (scheduler, 30 s): expire requests, release quarantine (10 min), cancel the
   unpaid attempts — their top-ups then expire.

## Admin

`/admin/p2p/{cards,incoming,requests,settings}` and `POST /admin/p2p/incoming/{id}/credit`
(«Зачислить пользователю»: refused twice and while a request holds that card and amount).

## Metrics and alerts

`csmarket_p2p_notifications_total{result}`, `csmarket_p2p_alerts_total{kind}`,
`csmarket_p2p_requests_expired_total`, `csmarket_p2p_last_notification_timestamp_seconds`;
alerts `P2PUnparsed`, `P2PChainBreak`, `P2PAmbiguousCard`, `P2PSilence`
(`infra/prometheus/alerts/p2p.yml`).
