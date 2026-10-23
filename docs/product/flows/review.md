# Flow — a review after a deal

Spec `docs/superpowers/specs/2026-10-23-reviews-design.md`, ADR-0023.

## What the user sees

- **The moment the deal succeeds** — the buyer accepted the trade (market), the 7-day hold ended
  and the money is on the balance, or an admin paid the card (buy-back) — a modal opens on
  whatever page of the site is open: the skin's picture, «Обмен прошёл! Как вам покупка?» (a sale:
  «Как прошла продажа?»), five stars and an optional text. The placeholder follows the stars: 1–3
  «Расскажите, что случилось?», 4–5 «Пару тёплых слов — это нам очень помогает». «Отправить» or
  «Не сейчас». After sending: a thank-you; 1–3 stars add «Мы свяжемся с вами».
- **On a later visit**, a deal without a review shows a bottom strip «Как прошла покупка <скин>?»
  with stars, once per visit. «Не сейчас» hides it for 3 days, × for good. Nothing is asked 14
  days after the deal.
- **In the account**, a delivered order or a paid sale shows «Оставить отзыв» or the stars given;
  the review can be changed for 14 days.
- **`/reviews`** says «Скоро» until the owner switches the page on; then it lists the 4–5★ reviews,
  the visitor's language first.

## Sequence

```mermaid
sequenceDiagram
    autonumber
    participant W as Worker / admin
    participant DB as Postgres
    participant API as API (realtime)
    participant B as Browser (any page)
    W->>DB: order delivered / sale credited / payout paid + pg_notify
    DB-->>API: NOTIFY order_events
    API-->>B: {"type":"order.changed"|"sale.updated"}
    B->>API: GET /reviews/pending
    API-->>B: {deal} (succeeded during this visit)
    B->>B: open the modal
    B->>API: PUT /reviews/{kind}/{number} (Idempotency-Key)
    API->>DB: lock the deal, insert / update the review
    API-->>B: DealReviewOut
    Note over B,API: a bad review lands in the admin's «Плохие»;<br/>a good one shows on /reviews once the page is on
```
