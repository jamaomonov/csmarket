# Runbook — First deploy to a fresh VPS

The one-time bootstrap that brings csmarket up on its own Ubuntu 24.04 server. Every release
after this one follows [`deploy.md`](deploy.md).

Target: **csmarket.uz** on one VPS (4 vCPU / 8 GB RAM / ≥ 80 GB SSD), the whole stack in
`docker-compose.prod.yml`, its own Caddy on `:80`/`:443`, Cloudflare in front (ADR-0003).

> Nothing here runs without the owner's explicit word: a push, a workflow run and a deploy
> each need it (`AGENTS.md` § 14).

---

## 0. Prerequisites

- [ ] Domain `csmarket.uz` in Cloudflare (the zone is active, DNS managed there).
- [ ] VPS ordered: Ubuntu 24.04, public IPv4 known, provider snapshots on.
- [ ] An SSH keypair on the operator's laptop.
- [ ] GitHub repo `jamaomonov/csmarket` exists, `main` pushed.
- [ ] Sentry project for csmarket and its DSN (optional for M0; empty disables Sentry).

Not needed for M0 — they belong to M5 (launch) and switch on the `alerts` and `ops` compose
profiles
([step 9](#9-alerts-first-backups-later-m5)):

- [ ] An **age keypair for backups**, made on the operator's laptop, never on the server:
      `age-keygen -o ~/csmarket-backup.key`. The public `age1…` line goes to the server; the
      `AGE-SECRET-KEY-…` line stays offline — without it no backup can be read.
- [ ] Cloudflare R2 bucket **`csmarket-backups`** and an R2 API token scoped to that bucket
      only (details: `infra/secrets-example/README.md`).
- [ ] Ops Telegram chat id and an alert bot token whose bot is a member of that chat.

---

## 1. DNS and TLS mode in Cloudflare

Point five records at the VPS, **proxied** (orange cloud):

| Type | Name       | Value      |
| ---- | ---------- | ---------- |
| A    | `@` (apex) | `<VPS_IP>` |
| A    | `www`      | `<VPS_IP>` |
| A    | `api`      | `<VPS_IP>` |
| A    | `admin`    | `<VPS_IP>` |
| A    | `grafana`  | `<VPS_IP>` |

`www` only redirects to the apex, but Caddy requests a certificate for it, so it needs a record.

SSL/TLS → Overview → encryption mode **Full (strict)**. "Flexible" talks cleartext to an
HTTPS origin and loops the redirect. Leave **Always Use HTTPS off** until step 7: with it on,
Cloudflare answers the Let's Encrypt HTTP challenge with a redirect to HTTPS, which the origin
cannot serve before it has a certificate.

---

## 2. Server bootstrap

Everything that needs root happens **as root, before** the switch to `deploy`. `deploy` gets
no sudo at all: it runs Docker through the `docker` group, and nothing later in this runbook
or in `deploy.yml` needs more.

Keep this root session open until step 2c says otherwise.

### 2a. As root: user, Docker, firewall

```bash
ssh root@<VPS_IP>          # or the provider's user, then `sudo -i`

# Non-root deploy user, logging in with the same key you used for root
# (for a provider user, copy /home/<that user>/.ssh/authorized_keys instead).
adduser --disabled-password --gecos "" deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
install -m 600 -o deploy -g deploy /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys

# Docker Engine with the Compose plugin.
apt-get update
apt-get install -y ca-certificates curl gnupg git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker deploy

# Firewall: SSH, HTTP, HTTPS only. 22 is allowed before enabling, so this session survives.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

### 2b. Second terminal: confirm `deploy` works

Leave the root session open. In a **new** terminal on your laptop:

```bash
ssh deploy@<VPS_IP>
docker ps                  # an empty table, no "permission denied"
docker compose version
```

Do not go on until both commands work. If the login fails, fix it from the root session
(`authorized_keys` ownership and mode are the usual cause).

### 2c. Back in the root session: harden SSH

Only now turn off root and password logins. A drop-in under `sshd_config.d/` named `00-…`
wins over the image's own drop-ins (sshd keeps the first value it reads, and Ubuntu cloud
images ship `50-cloud-init.conf`, which may enable passwords):

```bash
cat > /etc/ssh/sshd_config.d/00-csmarket.conf <<'CFG'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
CFG
sshd -t                                            # must print nothing
sshd -T | grep -Ei '^(permitrootlogin|passwordauthentication) '   # both "no"
systemctl restart ssh
```

From the second terminal, open one more fresh `ssh deploy@<VPS_IP>` to prove the restarted
daemon still lets `deploy` in. Only then close the root session. From here on, work as
`deploy`.

### 2d. As `deploy`: the checkout

Clone the repo with a **read-only deploy key** (GitHub → repo → Settings → Deploy keys), so a
compromised box cannot push:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/csmarket_deploy -N "" -C "csmarket-vps"
cat ~/.ssh/csmarket_deploy.pub     # add as a deploy key, write access OFF
cat >> ~/.ssh/config <<'CFG'
Host github.com
  IdentityFile ~/.ssh/csmarket_deploy
  IdentitiesOnly yes
CFG
install -d ~/opt
git clone git@github.com:jamaomonov/csmarket.git ~/opt/csmarket
```

The path matters: `.github/workflows/deploy.yml` runs `cd "$HOME/opt/csmarket"`.

If the GHCR packages are private (the default for a private repo), log the server in once
with a classic token that has only `read:packages`:

```bash
echo '<token>' | docker login ghcr.io -u jamaomonov --password-stdin
```

---

## 3. Secrets

`docker-compose.prod.yml` reads `./secrets/*.env` — git-ignored, inside the checkout, owned by
`deploy`. `infra/secrets-example/README.md` explains every file and how to generate each value.

```bash
cd ~/opt/csmarket
install -d -m 0700 secrets
cp infra/secrets-example/*.env secrets/
# M0 needs these seven; replace every CHANGE_ME in them:
M0_SECRETS="postgres postgres-exporter redis api web caddy grafana"
for f in $M0_SECRETS; do $EDITOR "secrets/$f.env"; done
chmod 600 secrets/*.env
for f in $M0_SECRETS; do grep -Hn 'CHANGE_ME' "secrets/$f.env"; done   # must print nothing
```

`backup.env` and `alertmanager.env` keep their placeholders until M5: the services that read
them are in the `ops` profile (Alertmanager also in `alerts`) and do not start before step 9 enables it. Compose still wants
the files to exist, so copy them anyway.

Keep an offline copy of `CSMARKET_APP_ENC_KEY`: the server holds the only one, and losing it
makes every encrypted row unreadable (and every email confirmation link in flight).

Email (M4b, owner action): in Resend add the domain `csmarket.uz`, put its SPF and DKIM
records into Cloudflare DNS (DNS only), and create a key with sending access to that domain;
put it in `secrets/api.env` as `CSMARKET_RESEND_API_KEY` (`CSMARKET_EMAIL_TRANSPORT=resend`
is already there). Without a key the API warns at start-up and letters retry, then fail
(`EmailsFailing`) — money and orders are unaffected. [`email.md`](./email.md).

---

## 4. GitHub

1. Repo → Settings → Secrets and variables → Actions: add **`DEPLOY_HOST`** (the VPS IP),
   **`DEPLOY_USER`** (`deploy`) and **`DEPLOY_SSH_KEY`** (a private key whose public half is in
   `~deploy/.ssh/authorized_keys` — a dedicated key, not your personal one).
2. **Build images** (`.github/workflows/build.yml`) runs on every push to `main`; run it by
   hand from the Actions tab if it has not. It pushes
   `ghcr.io/jamaomonov/csmarket-{api,worker,scheduler,web,admin}`.
3. Note the image tag: `sha-` + the first 7 characters of the built commit
   (`git rev-parse --short=7 origin/main`), e.g. `sha-1a2b3c4`.

---

## 5. First start, by hand

```bash
cd ~/opt/csmarket
# Pin the tag from step 4 in the checkout's git-ignored .env; compose reads it on every
# command, and refuses to run without it. Every later deploy rewrites this line.
printf 'IMAGE_TAG=%s\n' sha-1a2b3c4 > .env

docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml up -d --remove-orphans
docker compose -f docker-compose.prod.yml ps
```

Watch Caddy obtain certificates — one `certificate obtained successfully` per host:

```bash
docker compose -f docker-compose.prod.yml logs -f caddy
```

If one host keeps failing its ACME challenge, set that record to **DNS only** (grey cloud),
wait for the certificate, then switch the proxy back on.

Check, from your laptop:

```bash
curl -fsS https://api.csmarket.uz/healthz                                  # {"status":"ok"}
curl -fsS https://api.csmarket.uz/readyz                                   # {"status":"ready",…}
curl -s -o /dev/null -w '%{http_code}\n' https://csmarket.uz/              # 200 — the hello page
curl -s -o /dev/null -w '%{http_code}\n' https://www.csmarket.uz/          # 301 → apex
curl -s -o /dev/null -w '%{http_code}\n' https://admin.csmarket.uz/        # 200
curl -s -o /dev/null -w '%{http_code}\n' https://api.csmarket.uz/metrics   # 404 — internal only
```

And on the server, that every app container runs the tag you meant:

```bash
for s in api worker scheduler web admin; do
  docker inspect "csmarket-prod-$s-1" --format '{{.Config.Image}}'
done
```

`https://csmarket.uz/` answering the hello page from these images is M0's done-criterion.

---

## 5a. Search indexing stays closed

`secrets/caddy.env` must say `CSMARKET_INDEXING=off` (the example does): the storefront stays
out of search until the owner opens it. Check: `curl -sI https://csmarket.uz/ | grep -i
x-robots-tag` prints `noindex, nofollow`. Opening it: `docs/runbooks/indexing.md`.

---

## 6. Grafana

Open `https://grafana.csmarket.uz/`. Caddy asks for basic-auth first (user `ops`, the
password whose bcrypt hash is `GRAFANA_BASIC_AUTH_HASH` in `secrets/caddy.env`), then Grafana
shows its own login (`GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` from
`secrets/grafana.env`). Datasources and dashboards are provisioned from `infra/grafana/`.
Logs: Explore → Loki → `{container=~"csmarket-prod-.*"}`.

---

## 7. Cloudflare settings

Once every host has its certificate:

- SSL/TLS → Edge Certificates → **Always Use HTTPS: on**.
- **No cache rule that drops the query string from the cache key** on storefront paths.
  Next.js fetches `?_rsc=…` payloads from the same URLs as the HTML; a key without the query
  string can serve that payload to a visitor as the page (a lesson carried over from YuPay).
- No WAF challenge or Bot Fight Mode on **`api.csmarket.uz`**. From M3 the acquirers' webhooks
  arrive there, and a challenge page is an unanswered webhook.
- Network → **WebSockets: on** (the default) — the order page uses `wss://api.csmarket.uz`
  from M4.

---

## 8. Verify the client IP

The rate limiter (and `ip_guard` from M1) keys on the first `X-Forwarded-For` entry, which
Caddy must overwrite with the visitor's address (ADR-0003). Check what the API actually
receives without writing any address to a log — watch the header on the wire inside the api
container's network namespace, on the server:

```bash
cd ~/opt/csmarket
docker run --rm -it --net "container:$(docker compose -f docker-compose.prod.yml ps -q api)" \
  nicolaka/netshoot tcpdump -A -s0 -l 'tcp dst port 8000' | grep -i 'x-forwarded-for'
```

Meanwhile, from your laptop:

```bash
# Through Cloudflare, with a forged header:
curl -s -o /dev/null https://api.csmarket.uz/healthz -H 'X-Forwarded-For: 1.2.3.4'
# Straight to the origin, forging both headers:
curl -sk -o /dev/null --resolve api.csmarket.uz:443:<VPS_IP> https://api.csmarket.uz/healthz \
  -H 'X-Forwarded-For: 1.2.3.4' -H 'Cf-Connecting-Ip: 5.6.7.8'
```

Each request must show **exactly one** `X-Forwarded-For` line carrying your own public
address — never `1.2.3.4`, never `5.6.7.8`, never a Cloudflare address. Stop `tcpdump` with
Ctrl-C; nothing was stored. A Cloudflare address means its ranges in `Caddyfile.prod` are
stale; a forged value means `header_up X-Forwarded-For {client_ip}` is missing from a site
block.

---

## 9. Alerts first, backups later (M5)

Not part of M0. Alertmanager is in the compose profiles `alerts` and `ops`; `backup` is in
`ops` only. Both would fail on placeholder secrets (Alertmanager crash-loops, the nightly
backup fails), so they start only when the profile is switched on. Until then Prometheus
keeps evaluating the rules and just logs that it cannot reach Alertmanager. Alerts come
first because they need only the Telegram bot; the backup needs the R2 bucket and the age key.

### 9a. Alerts

1. Fill in `secrets/alertmanager.env` on the server (the owner does it, never in chat);
   `chmod 600 secrets/alertmanager.env`.
2. Turn the `alerts` profile on in the same `.env` that pins the tag (deploys keep this line),
   and start Alertmanager:

   ```bash
   cd ~/opt/csmarket
   echo 'COMPOSE_PROFILES=alerts' >> .env
   docker compose -f docker-compose.prod.yml up -d alertmanager
   ```

3. Prometheus targets must all be up, and a test alert must reach the ops chat with the
   `[csmarket]` prefix:

   ```bash
   docker compose -f docker-compose.prod.yml exec -T prometheus \
     wget -qO- http://localhost:9090/api/v1/targets | grep -o '"health":"[a-z]*"' | sort | uniq -c
   docker compose -f docker-compose.prod.yml exec -T alertmanager \
     amtool alert add csmarket_first_deploy_test severity=warn --alertmanager.url=http://localhost:9093
   ```

   The test alert resolves by itself after a few minutes.

### 9b. Backups

With the age key and the R2 bucket and token from step 0:

1. Fill in `secrets/backup.env`; `chmod 600`; `grep -RIn 'CHANGE_ME' secrets/` must now print
   nothing at all.
2. Switch the profile to `COMPOSE_PROFILES=alerts,ops` (or just `ops`, which includes
   Alertmanager) in `.env` and start the backup:

   ```bash
   cd ~/opt/csmarket
   sed -i 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=alerts,ops/' .env
   docker compose -f docker-compose.prod.yml up -d
   ```

3. The `backup` service runs `pg_backup.sh` every night at `BACKUP_HOUR_UTC` (02:00 UTC by
   default). Run it once now and look at the result:

   ```bash
   docker compose -f docker-compose.prod.yml exec -T backup bash /scripts/pg_backup.sh
   docker compose -f docker-compose.prod.yml exec -T backup rclone ls r2:csmarket-backups
   ```

---

## Done

- Five hostnames serve valid certificates through Cloudflare (Full (strict)).
- `/healthz` and `/readyz` answer; the storefront serves the hello page; admin loads.
- The API sees the visitor's real address and nothing else.
- From M5 (step 9): a backup sits in R2; alerts reach the ops Telegram chat.

Next: routine releases — [`deploy.md`](deploy.md); something slow — [`traffic-surge.md`](traffic-surge.md);
something broken — open an incident from [`incident-template.md`](incident-template.md).
