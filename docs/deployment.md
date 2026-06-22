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
│  - rate-limits /api/ + /admin│
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
        /run/secrets/ (API keys, passwords — file-mounted)
```

Defined in `docker-compose.prod.yml`:

- **`web`** — built from the root `Dockerfile` (`uv sync --no-dev`, runs
  `uvicorn main:app --port 8000`). `DB_DIR=/data` so SQLite persists on the
  `db_data` volume. Has a healthcheck (`curl -f http://localhost:8000/`).
  Secrets are mounted as files via Docker Compose secrets (not env vars).
- **`nginx`** — `nginx:1.27-alpine`, config rendered from `nginx/app.conf.template`.
  Terminates TLS, sets security headers, rate-limits sensitive endpoints, serves
  `frontend/static/` directly, and proxies everything else to `web`. Waits for `web`'s
  healthcheck before starting.
- **`certbot`** — runs `certbot renew --quiet` every 12 hours against the
  `certbot_conf`/`certbot_www` volumes shared with `nginx`.

## Prerequisites

- A Hetzner CX22 (or similar) Ubuntu 24.04 server with SSH access
- A domain with an A record pointing at the server's IP
- Locally: `make`, `ssh`, `scp`, `ssh-copy-id`

---

## Secrets Strategy

### The Problem

A flat `.env` file on the server is risky:

- One misconfigured `docker compose` flag or shell expansion leaks everything
- Any process in the container can read all env vars via `/proc/1/environ`
- `docker inspect` shows env vars in plaintext to anyone with Docker access
- A stray `printenv` or crash dump exposes keys

### The Solution: Docker Compose File Secrets

Secrets are stored as **individual files** on the server under `$DEPLOY_DIR/secrets/`,
mounted read-only into the container at `/run/secrets/<name>`. The app reads them from
files, not environment variables.

```
/opt/zdenovo/secrets/           ← chmod 700, owned by root
├── anthropic_api_key           ← one secret per file, chmod 600
├── unsplash_access_key
├── admin_password
└── secret_key
```

**Why this approach over alternatives:**

| Approach | Verdict |
|----------|---------|
| `.env` file | Dangerous — leaked via `docker inspect`, `/proc`, shell expansion |
| Docker Swarm secrets | Requires swarm mode — overkill for a single server |
| HashiCorp Vault | Enterprise-grade, needs its own server — overkill |
| Cloud KMS (AWS/GCP) | Wrong cloud, adds vendor lock-in |
| SOPS/age encrypted files | Good for git, but still decrypts to env vars |
| **Docker Compose file secrets** | **Right fit — simple, secure, no extra deps** |

### How It Works in `docker-compose.prod.yml`

```yaml
secrets:
  anthropic_api_key:
    file: ./secrets/anthropic_api_key
  # ...

services:
  web:
    secrets:
      - anthropic_api_key
      - unsplash_access_key
      - admin_password
      - secret_key
```

Docker mounts each secret as a read-only file at `/run/secrets/<name>` inside the
container. The Python app reads them with a helper:

```python
def _read_secret(name: str, env_fallback: str = "") -> str:
    secret_path = Path(f"/run/secrets/{name}")
    if secret_path.exists():
        return secret_path.read_text().strip()
    return os.environ.get(env_fallback, "")
```

This gives **dual-mode support**: prod reads files, dev reads `.env` via `load_dotenv()`.

### Secret Categories

| Secret | Runtime? | Stored as |
|--------|----------|-----------|
| `ANTHROPIC_API_KEY` | Yes — Claude API calls | `/run/secrets/anthropic_api_key` |
| `UNSPLASH_ACCESS_KEY` | Yes — hero images | `/run/secrets/unsplash_access_key` |
| `ADMIN_PASSWORD` | Yes — admin login | `/run/secrets/admin_password` |
| `SECRET_KEY` | Yes — session cookies | `/run/secrets/secret_key` |
| `DOMAIN` | Config, not secret | Server `.env` |
| `CERTBOT_EMAIL` | Config, not secret | Server `.env` |
| `SERVER_HOST` | Local only | Local `.env` (never on server) |
| `SERVER_USER` | Local only | Local `.env` (never on server) |
| `DEPLOY_DIR` | Local only | Local `.env` (never on server) |
| `REPO_URL` | One-time setup | Local `.env` (never on server) |

---

## One-Time Setup

### 1. Local `.env`

```bash
cp .env.example .env
# Fill in ALL values — secrets here are used for local dev
# and pushed to server as files on first deploy
```

### 2. First Deploy

```bash
make deploy-first
```

This command (run from your local machine):

1. Copies your SSH key to the server (`ssh-copy-id`)
2. Runs `scripts/server-setup.sh` on the server — updates packages, installs
   Docker Engine + Compose plugin, configures UFW (allows SSH, 80, 443), and
   clones `REPO_URL` into `DEPLOY_DIR`
3. Creates `$DEPLOY_DIR/secrets/` on the server (chmod 700) and writes each
   secret from your local `.env` into its own file (chmod 600)
4. Copies a minimal `.env` with only `DOMAIN` + `CERTBOT_EMAIL` to the server
5. Runs `make cert-init` on the server — bootstraps HTTP-only nginx, requests a
   Let's Encrypt cert, then switches to HTTPS
6. Runs `make prod` on the server — builds and starts the full stack

### 3. Rotating a Secret

```bash
# Update a single secret on the server and restart
make secret-set NAME=anthropic_api_key VALUE=sk-ant-new-key-here
```

Or manually:

```bash
ssh root@YOUR_SERVER
echo 'new-key-value' > /opt/zdenovo/secrets/anthropic_api_key
chmod 600 /opt/zdenovo/secrets/anthropic_api_key
cd /opt/zdenovo && docker compose -f docker-compose.prod.yml restart web
```

---

## Ongoing Deploys

```bash
make deploy
```

SSHes in and runs `cd $DEPLOY_DIR && git pull --ff-only && make prod`. The
`--ff-only` pull means the server's `main` must not have diverged — never commit
directly on the server. **Secrets are not touched during code deploys.**

---

## SSL Certificates

- **`make cert-init`** — first-time bootstrap (see above); also re-run if you
  change `DOMAIN`.
- **`make cert-renew`** — force an immediate renewal and reload nginx. Normally
  unnecessary: the `certbot` container renews automatically every 12 hours.

---

## Local Development

```bash
make dev        # docker compose up --build -d → http://localhost:8080
make dev-logs   # tail logs
make dev-down   # stop and remove dev containers
```

Uses the root `docker-compose.yml` (single `web` service, no nginx/TLS), maps
container port 8000 → host port 8080. The local `.env` is bind-mounted into the
container so `load_dotenv()` picks up secrets. Data lives in `./data/` (bind mount).

**Dev uses `.env` for convenience. Prod uses file secrets. The app supports both.**

---

## Make Targets Reference

| Target | Where | Purpose |
|--------|-------|---------|
| `make dev` / `dev-logs` / `dev-down` | local | Dev stack on `:8080` |
| `make test` | local | `cd backend && uv run pytest --cov` |
| `make prod` | server (or via `make deploy`) | Build + start the production stack |
| `make prod-logs` | server | Tail production logs |
| `make prod-stop` / `prod-down` | server | Stop/remove prod containers (data preserved) |
| `make cert-init` | server | Bootstrap SSL certificate (first time only) |
| `make cert-renew` | server | Force certificate renewal |
| `make check` | local | Health check: HTTPS, HTTP→HTTPS redirect, `/api/posts` |
| `make deploy-first` | local | One-time server setup + first deploy |
| `make deploy` | local | `git pull --ff-only && make prod` on the server |
| `make deploy-restart` | local | Restart prod containers (picks up secret changes) |
| `make secret-set` | local | Update a single secret on the server |
| `make backup` | local | Download `blog.db` backup from server |

---

## Environment Variables

### Server `.env` (non-secret config only)

| Variable | Example | Used by |
|----------|---------|---------|
| `DOMAIN` | `yourdomain.com` | `nginx/app.conf.template`, certbot |
| `CERTBOT_EMAIL` | `you@yourdomain.com` | `make cert-init` (Let's Encrypt) |

### Local `.env` (everything for dev convenience)

| Variable | Example | Used by |
|----------|---------|---------|
| `DOMAIN` | `yourdomain.com` | Makefile targets |
| `CERTBOT_EMAIL` | `you@yourdomain.com` | Makefile targets |
| `SERVER_HOST` | `1.2.3.4` | `make deploy*` (SSH target) |
| `SERVER_USER` | `root` | `make deploy*` (SSH user) |
| `DEPLOY_DIR` | `/opt/zdenovo` | `make deploy*` (clone dir) |
| `REPO_URL` | `https://github.com/youruser/zdenovo.git` | `server-setup.sh` |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Dev: env var. Prod: file secret |
| `UNSPLASH_ACCESS_KEY` | `your-key` | Dev: env var. Prod: file secret |
| `ADMIN_PASSWORD` | `change-me` | Dev: env var. Prod: file secret |
| `SECRET_KEY` | `random-hex` | Dev: env var. Prod: file secret |

---

## Production Hardening Checklist

- [ ] No `.env` with secrets on the server — only `DOMAIN` + `CERTBOT_EMAIL`
- [ ] All API keys in `$DEPLOY_DIR/secrets/` with chmod 600
- [ ] `secrets/` directory is chmod 700, owned by root
- [ ] `ADMIN_PASSWORD` is strong (not "admin")
- [ ] `SECRET_KEY` is random 64-char hex
- [ ] TLS 1.2+ only, HSTS enabled (nginx template)
- [ ] Rate limiting on `/api/` and `/admin/` (nginx template)
- [ ] `proxy_read_timeout 180s` (Claude generation takes 1-2 min)
- [ ] UFW active: only SSH (22), HTTP (80), HTTPS (443) open
- [ ] SSH key-only auth (disable password login after first deploy)
- [ ] Automated daily backup of `blog.db`
- [ ] `restart: unless-stopped` on all containers

---

## Health Check

```bash
make check
```

Verifies `https://$DOMAIN/` returns 200, `http://$DOMAIN/` redirects (301/302),
and `https://$DOMAIN/api/posts` returns valid JSON.

---

## Data Persistence & Backup

`blog.db` lives in the `db_data` Docker volume at `/data/blog.db`. To back it up:

```bash
# From local machine
make backup

# Or manually on the server
docker compose -f docker-compose.prod.yml exec web cat /data/blog.db > blog.db.bak
```

`make prod-down` / `prod-stop` preserve volumes. Only `docker compose down -v`
removes `db_data` (resetting to `seed_posts.json` on next startup).
