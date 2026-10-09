# Runbook — Deploy

Routine releases after the [first deploy](first-deploy.md). **Only on the owner's explicit
command in that message** (`AGENTS.md` § 14).

## The normal path

1. The change is merged to `main` and **Build images** (`.github/workflows/build.yml`) is
   green. Its image tag is `sha-` + the commit's first 7 characters
   (`git rev-parse --short=7 origin/main`).
2. Dispatch **Deploy** (`.github/workflows/deploy.yml`) with that tag:

   ```bash
   make deploy tag=sha-1a2b3c4
   # same as: gh workflow run deploy.yml -f environment=production -f image_tag=sha-1a2b3c4
   ```

   (or Actions → Deploy → Run workflow). A release tag `vX.Y.Z` works the same way — its
   images carry the git tag verbatim. `main` also works but is a moving tag; prefer the
   pinned `sha-` tag.

3. The workflow, over SSH in `~/opt/csmarket`: fetches, checks out **the commit the tag
   names** (`sha-1a2b3c4` → commit `1a2b3c4`, `vX.Y.Z` → that git tag, `main` →
   `origin/main`; a tag that resolves to nothing fails the deploy), `pull`s, runs
   `alembic upgrade head` in a one-shot `api` container, writes `IMAGE_TAG=<tag>` into the
   checkout's `.env`, `up -d --remove-orphans`, recreates `caddy` when
   `infra/caddy/Caddyfile.prod` changed, waits for `https://api.csmarket.uz/healthz`,
   `/readyz` and `https://csmarket.uz/`, then prunes old images (keeping three per service).

Because the checkout follows the tag, `docker-compose.prod.yml`, the Caddyfile and the alert
rules on the server always match the images that run.

Deploys are stop-then-start, not rolling: expect a few seconds of held requests (Caddy retries
for 15 s). Migrations run before the new code starts, so the old code briefly serves against
the new schema — write migrations that the previous release tolerates.

## `IMAGE_TAG` lives in `~/opt/csmarket/.env`

`docker-compose.prod.yml` resolves images as `csmarket-<app>:${IMAGE_TAG}` and refuses to run
without it (`required variable IMAGE_TAG is missing a value`). The deploy workflow pins the
tag in the checkout's git-ignored `.env`, which compose reads on every command, so a manual
command reuses the deployed tag and never falls back to a stale cached `:main`:

```bash
cd ~/opt/csmarket
cat .env                                            # IMAGE_TAG=sha-1a2b3c4 (+ COMPOSE_PROFILES from M5)
docker compose -f docker-compose.prod.yml up -d api worker scheduler
docker inspect csmarket-prod-api-1 --format '{{.Config.Image}}'   # the same tag
```

Compose profiles: `alerts` = Alertmanager, `ops` = Alertmanager + backup. The server's `.env`
`COMPOSE_PROFILES` decides what runs.

Do not `export IMAGE_TAG=…` in a shell on the server: an exported value overrides `.env` and
is exactly how a hand-run command rolls a service back. To change the running tag, deploy.

## Rollback

Redeploy the previous `sha-` tag through the same workflow:

```bash
make deploy tag=sha-<previous>
```

The checkout moves back to that commit, so compose, the Caddyfile and alert rules roll back
with the images, and `.env` is rewritten to the old tag. The last three images per service
stay on the box, so the pull is instant. Schema rollbacks are not part of a normal rollback:
migrations are forward-only, and the previous release must tolerate the new schema. If data
has to go back, that is a restore from backup — ask the owner first.

## Changing a secret

Edit `secrets/<file>.env` on the server, then recreate the services that read it — **`up -d`,
never `restart`** (`restart` keeps the old environment). The tag comes from `.env`:

```bash
cd ~/opt/csmarket
docker compose -f docker-compose.prod.yml up -d api worker scheduler
docker compose -f docker-compose.prod.yml exec -T api printenv CSMARKET_BASE_URL   # confirm it landed
```

`secrets/api.env` is read by `api`, `worker` and `scheduler`. Details and rotation:
`infra/secrets-example/README.md`.

## Changing the Caddyfile by hand

It is a single-file bind mount; after editing, `up -d --force-recreate caddy` (a reload keeps
the old inode).

## After a deploy

```bash
curl -fsS https://api.csmarket.uz/healthz
curl -fsS https://api.csmarket.uz/readyz
docker compose -f docker-compose.prod.yml ps
```

Then glance at Grafana and the ops chat for the next few minutes.
