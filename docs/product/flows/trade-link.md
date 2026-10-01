# Flow — Save and check the trade link

The skin is sent to the buyer's Steam trade link, so every buyer saves one once, on the
account page.

## What the user sees

1. On `/account` the field «Ссылка на обмен» has a «Где взять?» hint that points to the
   place in Steam where the link is shown.
2. They paste the link and save. A link that is not a Steam trade link, or that belongs to
   another Steam account, is refused with a plain message; nothing is saved.
3. After saving, the page checks the link and shows one of:
   - **ok** — the link works;
   - **bad** — the link is invalid, the inventory is private, trading is banned, or Steam holds
     trades on the account (a hold is refused: the customer is told to turn on Steam Guard in the
     mobile app, and the link cannot be used to buy until the hold is gone) — it says which;
   - **no verdict** — the check was unavailable right now. The link stays saved.
4. They can run the check again at any time. A repeat within 10 minutes answers at once.

## Sequence

```mermaid
sequenceDiagram
    autonumber
    actor U as Signed-in user
    participant App as Account page
    participant API as API
    participant DB as Postgres
    participant R as Redis
    participant WP as Waxpeer
    participant Steam as Steam Web API

    U->>App: Paste trade link
    App->>API: PUT /me/trade-link {url} + Idempotency-Key
    API->>API: Parse partner and token
    API->>API: partner + 76561197960265728 must equal users.steam_id
    alt not the user's own link
        API-->>App: 422 trade_link_not_yours (nothing written)
    else own link
        API->>DB: Save link; a different link clears verdict, reason, checked_at
        API-->>App: 200 TradeLinkOut (verdict null)
    end

    App->>API: POST /me/trade-link/check (keyless, advisory)
    API->>R: ip_guard trade-link-check (IP + user)
    API->>R: GET users:tradelink:{sha256(link)[:32]}
    alt cache hit
        R-->>API: verdict, reason
    else miss
        API->>R: GET users:tradelink:breaker
        alt breaker open
            API->>API: verdict null, reason unavailable
        else closed
            Note over API,DB: Read transaction committed first: no connection held across the calls
            API->>WP: POST check-tradelink (4 s)
            API->>Steam: GetTradeHoldDurations (4 s)
            Note over API: Waxpeer reason gives bad (private, trade_ban, invalid).<br/>Non-zero hold gives bad (hold).<br/>Any failure opens the 60 s breaker.
            API->>R: SET verdict and reason, 600 s
        end
    end
    API->>DB: Record verdict and reason (checked_at only when a verdict exists)
    API-->>App: 200 TradeLinkOut
```

Source: `docs/architecture/sequence-diagrams/trade-link-check.mmd`.
Rules: spec §7.2; the token inside the link is a credential and is never logged
(`docs/security/pii-handling.md`).
