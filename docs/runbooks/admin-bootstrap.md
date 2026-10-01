# Runbook — Give someone admin access

An admin is a normal Steam account whose `users.roles` holds `admin`. There is no admin
password and no separate admin account (ADR-0004). The role is granted from the server, so
nobody can grant it to themselves through the site.

## Grant

1. The person opens `https://admin.csmarket.uz` and signs in with Steam. They see
   «Нет доступа» — that is expected. It creates their user row.
2. On the server, in `~/opt/csmarket` (`IMAGE_TAG` is already pinned in `.env`; do not
   export one by hand — `docs/runbooks/deploy.md`):

   ```bash
   docker compose -f docker-compose.prod.yml exec api \
     python -m csmarket.scripts.grant_admin --steam-id <17 digits>
   ```

   It prints `granted`. Other answers: `unchanged` (already an admin), `not_found` (exit 1:
   the person has not signed in yet), and exit 2 for a malformed ID. It never prints the ID.

3. The person reloads the admin. Roles are read from the database on every request, so no
   new sign-in is needed.

The Steam ID is the 17-digit SteamID64 (`7656119…`). Ask the person for it, or read it from
their Steam profile URL. Do not paste it into chat or tickets that outlive the task.

## Revoke

```bash
docker compose -f docker-compose.prod.yml exec api \
  python -m csmarket.scripts.grant_admin --steam-id <17 digits> --revoke
```

Prints `revoked`. The next admin request of that person answers 403.

Revoking the role does not end their sessions; they just lose access to the admin.

## Locally

Same script against the dev stack:

```bash
docker compose exec api python -m csmarket.scripts.grant_admin --steam-id 7656119XXXXXXXXXX
```

Or skip Steam: dev login with `admin: true` creates the account and the role in one step
(`docs/onboarding/local-setup.md`, "Signing in locally").

## If it does not work

- **Still «Нет доступа» after `granted`.** Reload the page. Check that the person signed in
  with the same Steam account as the ID you granted.
- **`not_found`.** The person has not completed a sign-in on this environment yet.
