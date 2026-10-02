# Flow — Confirm the email

Order letters (paid, trade sent, money back on the balance) go only to a confirmed address
(owner decision D1, ADR-0008).

## What the user sees

1. On `/account`, «Email — Для писем о заказах.» They enter an address and save: «Мы
   отправили письмо со ссылкой — откройте его.»
   A second address saved within a minute of the last letter is kept, but the page says
   «Отправить ещё раз можно через минуту.» — the letter goes out when they press the button.
2. Until it is confirmed: «Почта не подтверждена. Мы отправили письмо на {email}.» and
   «Отправить ещё раз» (once a minute; sooner → «Отправить ещё раз можно через минуту.»).
3. The letter «Подтвердите почту» has one button. It opens
   `/account/email/confirm?token=…` — on any device, signed in or not — which says «Почта
   подтверждена. Теперь письма о заказах будут приходить на неё.» and «В профиль». The
   token leaves the address bar at once.
4. A link older than 24 h: «Ссылка устарела. Отправьте письмо ещё раз в профиле.» A link for
   an address since changed, or a broken one: «Ссылка не подходит. Отправьте письмо ещё раз в
   профиле.»
5. Confirmed: the badge «Подтверждена». A new address starts over.

## Sequence

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant Web as Storefront
    participant API as API
    participant DB as Postgres
    participant W as Worker
    participant M as Mailbox

    U->>Web: save email on /account
    Web->>API: PATCH /me {email} (Idempotency-Key)
    API->>DB: email set, email_verified_at = null, outbox verify row (token sealed, 24 h) + NOTIFY
    API-->>Web: MeOut (email_verification_sent_at)
    W->>DB: claim the row, the address is still the user's and unverified
    W->>M: «Подтвердите почту» (via Resend)
    U->>Web: open the link
    Web->>API: POST /email/confirm {token}
    alt valid and the account's email is still the token's
        API->>DB: email_verified_at = now (once)
        API-->>Web: 200 {email_verified: true}
    else expired / invalid / stale
        API-->>Web: 422 email_token_expired / email_token_invalid, 409 email_token_stale
    end
```
