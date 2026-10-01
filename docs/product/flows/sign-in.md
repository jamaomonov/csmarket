# Flow — Sign in with Steam

Steam is the only sign-in. There is no registration form and no password.

## What the user sees

1. They click «Войти через Steam» in the header (ru / uz / en).
2. Steam's own page asks them to confirm. csmarket.uz is shown as the site.
3. They land on `/account` already signed in, with their Steam name and avatar. A brief
   «Входим через Steam…» screen shows while the callback is processed.
4. Next visits: still signed in for 30 days. Closing the tab does not sign them out.
5. If Steam says no or the link is stale, they see a short error and a button to try again
   (in the language they started in). A Steam return that was not started in this browser
   — for example a link someone else sent — never signs anyone in.
6. A suspended account sees a suspension notice instead of the account page. A ban ends every
   session, and each later visit asks again and is told the account is suspended, so the notice
   stays after a reload. Nothing about the ban is stored in the browser.

The admin (`admin.csmarket.uz`) uses the same sign-in. A signed-in person without the
`admin` role sees «Нет доступа».

## Sequence

```mermaid
sequenceDiagram
    autonumber
    actor U as Visitor
    participant App as App (web or admin)
    participant API as API
    participant Steam as Steam OpenID
    participant DB as Postgres
    participant R as Redis

    U->>App: Click "Sign in with Steam"
    App->>API: GET /auth/steam/start?app=web&locale=ru
    API->>API: Mint nonce n (token_urlsafe(16))
    API-->>U: 302 to Steam (return_to = app origin /auth/steam/callback?locale=ru&n=…) + Set-Cookie csmarket_oid=n (HttpOnly, 10 min)
    U->>Steam: Approve
    Steam-->>U: 302 back to the app callback with openid.* params (return_to signed)
    U->>App: /auth/steam/callback?locale&n&openid.*
    App->>App: Strip the params from the URL
    App->>API: POST /auth/steam {app, params: openid.*} + cookie csmarket_oid
    API->>R: ip_guard steam-login
    API->>API: Check claimed_id shape, openid.signed fields, return_to = our callback
    API->>API: Signed n == csmarket_oid cookie? (no → 401, nothing written)
    API->>Steam: check_authentication (10 s)
    Steam-->>API: is_valid:true
    API->>Steam: GetPlayerSummaries (5 s, best effort)
    API->>DB: Upsert user by steam_id, insert refresh_tokens (SHA-256)
    API-->>App: 200 {access_token} + Set-Cookie csmarket_refresh, csmarket_oid cleared
    App->>App: Keep the access token in memory

    Note over App,API: Later, page load or a 401
    App->>API: POST /auth/refresh (cookie)
    API->>DB: Rotate: revoke the old row, insert a new one
    alt owner banned (token revoked by the ban)
        API-->>App: 403 account-suspended (no writes)
    else token already rotated (reuse)
        API->>DB: Revoke every session of the user (reason reuse), commit
        API->>R: auth:revoked_sid for each session
        API-->>App: 401
    else token ended by logout, admin or an earlier reuse
        API-->>App: 401 (nothing else revoked)
    else normal
        API-->>App: 200 {access_token} + new cookie
    end
```

Source: `docs/architecture/sequence-diagrams/steam-sign-in.mmd`. Decision: ADR-0004.
