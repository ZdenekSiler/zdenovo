# Deployment Guide

zdenovo deploys to a single Hetzner (or any Ubuntu 24.04) VPS via Docker Compose,
automated end-to-end by the root `Makefile`. There is no PaaS, no Kubernetes — one
server, three containers.

## Architecture

```
Internet
   │
   ▼
┌─────────────────────────────┐
│ nginx (ports 80, 443)        │  ← TLS termination, serves /static directly
│  - redirects 80 → 443        │
│  - proxies / to web:8000     │
└──────────────┬────────────────┘
               │
               ▼
        ┌─────────────┐      ┌──────────────────────┐
        │ web          │      │ certbot               │
        │ FastAPI app  │      │ renews TLS cert       │
        │ (uvicorn)    │      │ every 12h             │
        └──────┬───────┘      └───────────────────────┘
               │
               ▼
        db_data volume (blog.db, SQLite)
```

Defined in `docker-compose.prod.yml`:

- **`web`** — built from the root `Dockerfile` (`uv sync --no-dev`, runs
  `uvicorn main:app --port 8000`). `DB_DIR=/data` so SQLite persists on the
  `db_data` volume. Has a healthcheck (`curl -f http://localhost:8000/`).
- **`nginx`** — `nginx:1.27-alpine`, config rendered from `nginx/app.conf.template`.
  Terminates TLS, sets security headers, serves `frontend/static/` directly, and
  proxies everything else to `web`. Waits for `web`'s healthcheck before starting.
- **`certbot`** — runs `certbot renew --quiet` every 12 hours against the
  `certbot_conf`/`certbot_www` volumes shared with `nginx`.

## Prerequisites

- A Hetzner CX22 (or similar) Ubuntu 24.04 server with SSH access
- A domain with an A record pointing at the server's IP
- Locally: `make`, `ssh`, `scp`, `ssh-copy-id`

## One-Time Setup

```bash
cp .env.example .env
# fill in DOMAIN, CERTBOT_EMAIL, SERVER_HOST, SERVER_USER, DEPLOY_DIR, REPO_URL,
# ANTHROPIC_API_KEY — see "Environment Variables" below

make deploy-first
```

`make deploy-first` (run from your local machine):

1. Copies your SSH key to the server (`ssh-copy-id`)
2. Runs `scripts/server-setup.sh` on the server — updates packages, installs
   Docker Engine + Compose plugin, configures UFW (allows SSH, 80, 443), and
   clones `REPO_URL` into `DEPLOY_DIR`
3. Copies your local `.env` to `$DEPLOY_DIR/.env` on the server
4. Runs `make cert-init` on the server — bootstraps an HTTP-only nginx config,
   requests a Let's Encrypt cert via certbot for `DOMAIN` and `www.DOMAIN`, then
   regenerates `nginx/app.conf` from the template with HTTPS enabled
5. Runs `make prod` on the server — builds and starts the full stack

## Ongoing Deploys

```bash
make deploy
```

SSHes in and runs `cd $DEPLOY_DIR && git pull --ff-only && make prod`. The
`--ff-only` pull means the server's `main` must not have diverged — never commit
directly on the server.

## SSL Certificates

- **`make cert-init`** — first-time bootstrap (see above); also re-run if you
  change `DOMAIN`.
- **`make cert-renew`** — force an immediate renewal and reload nginx. Normally
  unnecessary: the `certbot` container renews automatically every 12 hours.

## Local Development

```bash
make dev        # docker compose up --build -d → http://localhost:8080
make dev-logs   # tail logs
make dev-down   # stop and remove dev containers
```

Uses the root `docker-compose.yml` (single `web` service, no nginx/TLS), maps
container port 8000 → host port 8080, and passes `ANTHROPIC_API_KEY` through from
your local `.env`. Data lives in the `db_data` volume — `docker compose down -v`
removes it.

## Make Targets Reference

| Target | Where | Purpose |
|--------|-------|---------|
| `make dev` / `dev-logs` / `dev-down` | local | Dev stack on `:8080` |
| `make test` | local | `cd backend && uv run pytest --cov` |
| `make prod` | server (or via `make deploy`) | Build + start the production stack |
| `make prod-logs` | server | Tail production logs |
| `make prod-stop` / `prod-down` | server | Stop/remove prod containers (volumes preserved) |
| `make cert-init` | server | Bootstrap SSL certificate (first time only) |
| `make cert-renew` | server | Force certificate renewal |
| `make check` | local | Health check: HTTPS, HTTP→HTTPS redirect, `/api/posts` |
| `make deploy-first` | local | One-time remote setup + first deploy |
| `make deploy` | local | `git pull --ff-only && make prod` on the server |

## Environment Variables

Defined in `.env` (gitignored, copy from `.env.example`):

| Variable | Example | Used by |
|----------|---------|---------|
| `DOMAIN` | `yourdomain.com` | `nginx/app.conf.template`, `make check` |
| `CERTBOT_EMAIL` | `you@yourdomain.com` | `make cert-init` (Let's Encrypt registration) |
| `SERVER_HOST` | `1.2.3.4` | `make deploy*` (SSH target) |
| `SERVER_USER` | `root` | `make deploy*` (SSH user) |
| `DEPLOY_DIR` | `/opt/zdenovo` | `make deploy*`, `server-setup.sh` (clone/working dir) |
| `REPO_URL` | `https://github.com/youruser/zdenovo.git` | `server-setup.sh` (first clone) |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | `routers/generate_api.py` (draft generation) |

`DB_DIR=/data` is set by the `Dockerfile`/compose files directly — not part of `.env`.

## Health Check

```bash
make check
```

Verifies `https://$DOMAIN/` returns 200, `http://$DOMAIN/` redirects (301/302),
and `https://$DOMAIN/api/posts` returns valid JSON.

## Data Persistence & Backup

`blog.db` lives in the `db_data` Docker volume at `/data/blog.db`. To back it up:

```bash
docker compose -f docker-compose.prod.yml exec web cat /data/blog.db > blog.db.bak
```

`make prod-down` / `prod-stop` preserve volumes. Only `docker compose down -v`
removes `db_data` (resetting to `seed_posts.json` on next startup).
