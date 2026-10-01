# Runbook — Deploy

Routine releases after the [first deploy](first-deploy.md). **Only on the owner's explicit
command in that message** (`AGENTS.md` § 14).

## The normal path

1. The change is merged to `main` and **Build images** (`.github/workflows/build.yml`) is
   green. Its image tag is `sha-` + the commit's first 7 characters
   (`git rev-parse --short=7 origin/main`).
2. Dispatch **Deploy** (`.github/workflows/deploy.yml`) with that tag:

   ```bash
   gh workflow run deploy.yml -f environment=production -f image_tag=sha-1a2b3c4
   ```

   (or Actions → Deploy → Run workflow). `make deploy env=production` dispatches the same
   workflow with its default tag, `main` — a moving tag; prefer the pinned `sha-` tag.

3. The workflow, over SSH in `~/opt/csmarket`: fetches, checks out, `pull`s, runs
   `alembic upgrade head` in a one-shot `api` container, `up -d --remove-orphans` with
   `IMAGE_TAG` set, recreates `caddy` when `infra/caddy/Caddyfile.prod` changed, waits for
   `https://api.csmarket.uz/healthz`, `/readyz` and `https://csmarket.uz/`, then prunes old
   images (keeping three per service).

Deploys are stop-then-start, not rolling: expect a few seconds of held requests (Caddy retries
for 15 s). Migrations run before the new code starts, so the old code briefly serves against
the new schema — write migrations that the previous release tolerates.

### Infra files with a `sha-` deploy

A `sha-…` input is an image tag, not a git ref, so the workflow cannot check it out and falls
back to the server's local `main` — which `git fetch` does not move. When a release changes
`docker-compose.prod.yml`, the Caddyfile, alert rules or other files under `infra/`,
fast-forward the checkout first, then deploy:

```bash
ssh deploy@<VPS_IP> 'cd ~/opt/csmarket && git fetch && git checkout -B main origin/main'
```

## Any manual compose command on prod: `IMAGE_TAG` always

`docker-compose.prod.yml` resolves images as `csmarket-<app>:${IMAGE_TAG:-main}`. A command
without `IMAGE_TAG` falls back to whatever `:main` is cached locally and silently rolls the
deploy back. Read the running tag first, reuse it, and check after:

```bash
cd ~/opt/csmarket
export IMAGE_TAG="$(docker inspect csmarket-prod-api-1 --format '{{.Config.Image}}' | sed 's/.*://')"
docker compose -f docker-compose.prod.yml up -d api worker scheduler
docker inspect csmarket-prod-api-1 --format '{{.Config.Image}}'
```

## Rollback

Redeploy the previous `sha-` tag through the same workflow:

```bash
gh workflow run deploy.yml -f environment=production -f image_tag=sha-<previous>
```

The last three images per service stay on the box, so the pull is instant. Schema rollbacks
are not part of a normal rollback: migrations are forward-only, and the previous release must
tolerate the new schema. If data has to go back, that is a restore from backup — ask the owner
first.

## Changing a secret

Edit `secrets/<file>.env` on the server, then recreate the services that read it — **`up -d`,
never `restart`** (`restart` keeps the old environment):

```bash
cd ~/opt/csmarket
export IMAGE_TAG=<running tag>     # see above
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
