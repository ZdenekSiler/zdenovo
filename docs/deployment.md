# Deployment Guide

Complete guide for deploying zdenovo to a Hetzner VPS behind Cloudflare.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Infrastructure Stack](#infrastructure-stack)
- [Prerequisites](#prerequisites)
- [SSH Configuration](#ssh-configuration)
- [Secrets Strategy](#secrets-strategy)
- [First-Time Server Setup](#first-time-server-setup)
- [Day-to-Day Deploys](#day-to-day-deploys)
- [Quick Deploy via Claude Code](#quick-deploy-via-claude-code)
- [Cloudflare Configuration](#cloudflare-configuration)
- [nginx Configuration](#nginx-configuration)
- [SSL/TLS](#ssltls)
- [Database Management](#database-management)
- [Secret Rotation](#secret-rotation)
- [Monitoring and Health Checks](#monitoring-and-health-checks)
- [Troubleshooting](#troubleshooting)
- [Make Targets Reference](#make-targets-reference)
- [Environment Variables Reference](#environment-variables-reference)
- [Production Hardening Checklist](#production-hardening-checklist)

---

## Architecture Overview

```
 Browser
    │
    ▼
┌──────────────────────────────────────┐
│ Cloudflare (Flexible SSL)            │
│  - DNS proxy (orange cloud)          │
│  - HTTPS termination to client       │
│  - DDoS protection, caching          │
│  - Connects to origin over HTTP:80   │
└──────────────┬───────────────────────┘
               │ HTTP
               ▼
┌──────────────────────────────────────┐
│ Hetzner VPS (Ubuntu 24.04)           │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ nginx (port 80)                │  │
│  │  - rate limiting               │  │
│  │  - serves /static/ directly    │  │
│  │  - proxies everything else     │  │
│  │    to web:8000                 │  │
│  └──────────────┬─────────────────┘  │
│                 │                     │
│                 ▼                     │
│  ┌────────────────────────────────┐  │
│  │ web (FastAPI + uvicorn)        │  │
│  │  - reads /run/secrets/*        │  │
│  │  - writes to /data/blog.db    │  │
│  └──────────────┬─────────────────┘  │
│                 │                     │
│                 ▼                     │
│  db_data volume (SQLite)             │
│  /opt/zdenovo/secrets/ (API keys)    │
└──────────────────────────────────────┘
```

Traffic flow: Browser → Cloudflare (HTTPS) → nginx (HTTP:80) → FastAPI (HTTP:8000)

---

## Infrastructure Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Server | Hetzner CX22, Ubuntu 24.04 | VPS host |
| Containers | Docker + Docker Compose | Application runtime |
| Web framework | FastAPI + uvicorn | Python backend |
| Database | SQLite (Docker volume) | Blog posts, drafts |
| Reverse proxy | nginx 1.27-alpine | Rate limiting, static files, proxy |
| CDN/DNS | Cloudflare (free tier) | DNS, SSL termination, DDoS protection |
| Secrets | Docker Compose file secrets | `/run/secrets/*` inside container |
| Deployment | Git pull + Docker rebuild via SSH | No CI/CD pipeline needed |

Docker Compose runs two services in production (`docker-compose.prod.yml`):

- **`web`** — built from `Dockerfile` (Python 3.12-slim + uv), runs uvicorn on port 8000.
  SQLite DB persists on the `db_data` volume at `/data/blog.db`. Secrets mounted as
  read-only files at `/run/secrets/<name>`.
- **`nginx`** — nginx:1.27-alpine, listens on port 80. Serves `/static/` directly from a
  bind-mounted volume. Proxies all other requests to `web:8000`. Waits for web's
  healthcheck before starting.

A `certbot` service is defined for Let's Encrypt but is unused in the current Cloudflare
Flexible SSL setup (Cloudflare terminates HTTPS; origin is HTTP-only).

---

## Prerequisites

### Server

- Hetzner CX22 (or any Ubuntu 24.04 VPS with 2+ GB RAM)
- SSH access as root
- Public IPv4 address

### DNS

- Domain with Cloudflare DNS (free tier is fine)
- A record pointing to the server IP, **proxied** (orange cloud)
- www CNAME to the apex domain, **proxied**

### Local machine

- `make`, `ssh`, `git`
- Docker + Docker Compose (for local dev)
- Claude Code CLI (for `/deploy` skill)

---

## SSH Configuration

SSH access uses an alias defined in `~/.ssh/config` (local machine, not committed to git):

```
Host zdenovo
    HostName <server-ip>
    User root
    IdentityFile ~/.ssh/<your-key>
```

All deployment commands use `ssh zdenovo` — no hardcoded IPs or key paths in the
repository. Test with:

```bash
ssh zdenovo "echo OK"
```

The Makefile uses `SSH_CMD := ssh $(SERVER_USER)@$(SERVER_HOST)` from `.env` for the
`make deploy*` targets. Both approaches work — the SSH config alias is used by the
`/deploy` Claude Code skill, while the Makefile reads from `.env`.

---

## Secrets Strategy

### The Problem

A flat `.env` file on the server is dangerous:

- `docker inspect` shows env vars in plaintext to anyone with Docker access
- Any process inside the container reads all env vars via `/proc/1/environ`
- Shell expansion or a stray `printenv` in a script can leak everything
- A crash dump or debug log may capture the full environment

### The Solution: Docker Compose File Secrets

Secrets are stored as **individual files** on the server, mounted read-only into the
container at `/run/secrets/<name>`. The app reads them from files, never from environment
variables in production.

```
/opt/zdenovo/secrets/           ← chmod 700, owned by root
├── anthropic_api_key           ← one secret per file, chmod 600
├── unsplash_access_key
├── admin_password
└── secret_key
```

### How It Works

In `docker-compose.prod.yml`:

```yaml
secrets:
  anthropic_api_key:
    file: ./secrets/anthropic_api_key
  unsplash_access_key:
    file: ./secrets/unsplash_access_key
  admin_password:
    file: ./secrets/admin_password
  secret_key:
    file: ./secrets/secret_key

services:
  web:
    secrets:
      - anthropic_api_key
      - unsplash_access_key
      - admin_password
      - secret_key
```

Docker mounts each file at `/run/secrets/<name>` inside the container. The Python app
reads them with a dual-mode helper (`config.py`):

```python
def read_secret(name: str, env_fallback: str = "") -> str:
    secret_path = Path(f"/run/secrets/{name}")
    if secret_path.exists():
        return secret_path.read_text().strip()
    return os.environ.get(env_fallback or name.upper(), "")
```

- **Production**: reads `/run/secrets/<name>` (file exists in the container)
- **Local dev**: falls back to env var from `.env` via `load_dotenv()`

No code changes needed between environments.

### Why File Secrets Over Alternatives

| Approach | Verdict |
|----------|---------|
| `.env` file | Dangerous — leaked via `docker inspect`, `/proc`, shell expansion |
| Docker Swarm secrets | Requires swarm mode — overkill for a single server |
| HashiCorp Vault | Enterprise-grade, needs its own server |
| Cloud KMS (AWS/GCP) | Wrong cloud, adds vendor lock-in |
| SOPS/age encrypted files | Good for git, but still decrypts to env vars |
| **Docker Compose file secrets** | **Right fit — simple, secure, no extra dependencies** |

---

## First-Time Server Setup

### 1. Prepare local `.env`

```bash
cp .env.example .env
# Fill in all values — secrets here are used for local dev
# and pushed to server as files on first deploy
```

### 2. Set up SSH config

Add the server to `~/.ssh/config`:

```
Host zdenovo
    HostName <your-server-ip>
    User root
    IdentityFile ~/.ssh/<your-key>
```

Copy your SSH key to the server:

```bash
ssh-copy-id zdenovo
```

### 3. Run first deploy

```bash
make deploy-first
```

This single command:

1. Copies your SSH key to the server
2. Runs `scripts/server-setup.sh` on the server:
   - Updates packages
   - Installs Docker Engine + Compose plugin
   - Configures UFW firewall (SSH, HTTP, HTTPS only)
   - Clones the repository to `/opt/zdenovo`
3. Creates `/opt/zdenovo/secrets/` (chmod 700) and writes each secret from your
   local `.env` as an individual file (chmod 600)
4. Copies a minimal `.env` with only `DOMAIN` + `CERTBOT_EMAIL` to the server
5. Bootstraps SSL certificate (if using Let's Encrypt; skip for Cloudflare Flexible)
6. Builds and starts the production stack

### 4. Configure Cloudflare

See [Cloudflare Configuration](#cloudflare-configuration) below.

### 5. Write the nginx config on the server

When using Cloudflare Flexible SSL, the server only listens on HTTP:80. The template
(`nginx/app.conf.template`) is designed for direct Let's Encrypt HTTPS. For Cloudflare,
write a simplified HTTP-only config directly on the server:

```bash
ssh zdenovo
cat > /opt/zdenovo/nginx/app.conf << 'NGINX'
# Rate limiting zones
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=admin:10m rate=5r/s;
limit_req_zone $binary_remote_addr zone=login:10m rate=3r/m;

server {
    listen 80;
    server_name <your-domain> www.<your-domain>;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location /static/ {
        alias /app/frontend/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    location /admin/login {
        limit_req zone=login burst=5 nodelay;
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        client_max_body_size 1m;
    }

    location /admin/ {
        limit_req zone=admin burst=20 nodelay;
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
        proxy_connect_timeout 10s;
        client_max_body_size 5m;
    }

    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
        proxy_connect_timeout 10s;
        client_max_body_size 5m;
    }

    location / {
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        proxy_connect_timeout 10s;
        client_max_body_size 5m;
    }
}
NGINX
```

Reload nginx: `docker compose -f docker-compose.prod.yml exec nginx nginx -s reload`

### 6. Verify

```bash
curl -s -o /dev/null -w "%{http_code}" https://<your-domain>/
# Should return 200
```

---

## Day-to-Day Deploys

The standard deploy workflow:

```bash
# 1. Make changes locally
# 2. Run tests
make test

# 3. Commit
git add <files>
git commit -m "feat: description"

# 4. Push (pre-push hook runs full test suite including Playwright)
git push origin main

# 5. Deploy to server
ssh zdenovo "cd /opt/zdenovo && git pull --ff-only && docker compose -f docker-compose.prod.yml up --build -d web nginx"
```

Or use the Makefile:

```bash
make deploy   # SSHes in, git pulls, rebuilds containers
```

The `--ff-only` flag on `git pull` ensures the server branch has not diverged. Never
commit directly on the server.

### What happens during deploy

1. `git pull --ff-only` — fetches latest code from main
2. `docker compose up --build -d web nginx` — rebuilds the web image (only layers that
   changed), restarts both containers
3. nginx waits for web's healthcheck (Python urllib probe on `http://localhost:8000/`)
   before accepting traffic
4. Typical deploy time: 10-30 seconds

---

## Quick Deploy via Claude Code

The `/deploy` skill automates the full workflow:

```
/deploy                           # auto-generates commit message from diff
/deploy fix: update project list  # uses the provided commit message
```

What it does:

1. Checks for uncommitted changes and commits them
2. Pushes to main (test suite runs via pre-push hook)
3. SSHes to server, pulls, and rebuilds
4. Verifies the site is live (checks API response)
5. Reports: commit hash, build status, verification result

---

## Cloudflare Configuration

### DNS Records

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `@` (apex) | `<server-ip>` | Proxied (orange cloud) |
| CNAME | `www` | `<your-domain>` | Proxied (orange cloud) |

### SSL/TLS Settings

- **Encryption mode**: Flexible
  - Cloudflare handles HTTPS to the browser
  - Cloudflare connects to your origin over HTTP (port 80)
  - No SSL certificates needed on the server
- **Always Use HTTPS**: ON (redirects http:// to https://)
- **Minimum TLS Version**: 1.2

### Performance Settings

- **Rocket Loader**: OFF (or use `data-cfasync="false"` on critical scripts)
  - Rocket Loader defers JavaScript execution, which breaks Tailwind CDN and htmx
  - The site uses `data-cfasync="false"` on Tailwind and htmx script tags as a safeguard

### Why Flexible SSL (not Full)

With Cloudflare Flexible SSL:

- No Let's Encrypt certificate management needed on the server
- No certbot container, no renewal cron, no certificate expiry risk
- Simpler nginx config (HTTP-only, no TLS termination)
- The Cloudflare-to-origin hop is on Hetzner's internal network — acceptable risk for a
  personal blog

For sensitive applications, use **Full (Strict)** with a Cloudflare Origin Certificate
instead.

---

## nginx Configuration

Two nginx configs exist in the repo:

### `nginx/app.conf.template` (for Let's Encrypt / Full SSL)

- HTTP:80 redirects to HTTPS, serves ACME challenges
- HTTPS:443 with TLS termination, HSTS, ssl_stapling
- Used with `make cert-init` + certbot

### `nginx/app.conf` on the server (for Cloudflare Flexible)

- HTTP:80 only — Cloudflare handles HTTPS
- Written directly on the server (not generated from template)
- Survives `git pull` because `nginx/app.conf` is in `.gitignore`

### `nginx/no-default.conf`

An empty file mounted over `/etc/nginx/conf.d/default.conf` in the container. Without
this, nginx's built-in default server block intercepts requests before `app.conf` can
handle them.

### Rate Limiting

| Zone | Rate | Applied to | Purpose |
|------|------|-----------|---------|
| `login` | 3 req/min | `/admin/login` | Brute force protection |
| `admin` | 5 req/sec | `/admin/*` | Admin abuse protection |
| `api` | 10 req/sec | `/api/*` | API abuse protection |

### Timeouts

| Location | `proxy_read_timeout` | Why |
|----------|---------------------|-----|
| `/admin/login` | 10s | Simple form POST |
| `/admin/*` | 180s | Claude API generation can take 1-2 minutes |
| `/api/*` | 180s | Same — generation endpoints |
| `/` | 30s | Standard page loads |

---

## SSL/TLS

### Current Setup: Cloudflare Flexible

No certificates on the server. Cloudflare provides HTTPS to visitors. The origin
connection is HTTP-only.

### Alternative: Let's Encrypt (Full SSL)

If you switch to Cloudflare Full (Strict) or remove Cloudflare:

```bash
# On the server
cd /opt/zdenovo
make cert-init   # Bootstraps HTTP-only nginx, requests cert, switches to HTTPS

# The certbot container auto-renews every 12 hours
# Force renewal:
make cert-renew
```

The `nginx/app.conf.template` is already configured for this mode.

---

## Database Management

### Location

SQLite database lives in the `db_data` Docker volume, mounted at `/data/blog.db` inside
the web container.

### Backup

```bash
# From local machine
make backup   # Downloads blog.db to ./blog.db.bak

# Or manually
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml exec -T web cat /data/blog.db" > blog.db.bak
```

### Restore

```bash
# Copy local database to server
scp blog.db zdenovo:/tmp/blog.db

# Replace the database in the Docker volume
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml cp /tmp/blog.db web:/data/blog.db"
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml restart web"
```

### Reset to Seed Data

```bash
# On the server — removes the db_data volume entirely
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml down -v && docker compose -f docker-compose.prod.yml up --build -d web nginx"
```

The app inserts seed posts from `seed_posts.json` when the `posts` table is empty.

### Volume Safety

- `docker compose down` preserves volumes (data safe)
- `docker compose down -v` **deletes volumes** (data lost — only use intentionally)
- `docker compose stop` / `restart` never touch volumes

---

## Secret Rotation

### Rotate a single secret

```bash
# Via Makefile (from local machine)
make secret-set NAME=anthropic_api_key VALUE=sk-ant-new-key-here

# Or manually
ssh zdenovo
echo 'new-key-value' > /opt/zdenovo/secrets/anthropic_api_key
chmod 600 /opt/zdenovo/secrets/anthropic_api_key
cd /opt/zdenovo && docker compose -f docker-compose.prod.yml restart web
```

Secrets are read at request time (not cached at startup), so a container restart picks
up the new value immediately.

### When to rotate

- **Anthropic API key**: if leaked or compromised
- **Unsplash access key**: if leaked or compromised
- **Admin password**: periodically, or after sharing access
- **Secret key**: rotating invalidates all active sessions (users get logged out)

---

## Monitoring and Health Checks

### Container health

```bash
# From local machine
ssh zdenovo "docker compose -f /opt/zdenovo/docker-compose.prod.yml ps"
```

The web container has a built-in healthcheck:

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```

Uses Python's urllib instead of curl because `python:3.12-slim` doesn't include curl.

### Site health check

```bash
make check   # Verifies HTTPS, HTTP→HTTPS redirect, and API endpoint
```

### View logs

```bash
# All containers
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml logs --tail 50"

# Web container only
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml logs web --tail 30"

# Follow logs in real time
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml logs -f web"
```

### Container restart

```bash
# Restart web only (picks up secret changes)
make deploy-restart

# Restart both containers
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml restart"
```

---

## Troubleshooting

### Site returns Cloudflare error page

1. Check containers are running: `ssh zdenovo "docker ps"`
2. Check web container health: look for `(healthy)` in status
3. Check nginx can reach web: `ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml logs nginx --tail 20"`
4. Check if port 80 is open: `ssh zdenovo "ufw status"`

### Static files return 404

nginx needs the static files mounted as a volume. Check `docker-compose.prod.yml` has:

```yaml
nginx:
  volumes:
    - ./frontend/static:/app/frontend/static:ro
```

### nginx default page instead of app

The nginx default.conf intercepts requests. Ensure the empty override is mounted:

```yaml
nginx:
  volumes:
    - ./nginx/no-default.conf:/etc/nginx/conf.d/default.conf:ro
```

### Fonts look wrong / FOUC in production

Cloudflare Rocket Loader defers script execution, breaking Tailwind CDN. Ensure:

1. Critical scripts have `data-cfasync="false"`:
   ```html
   <script data-cfasync="false" src="https://cdn.tailwindcss.com"></script>
   <script data-cfasync="false" src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"></script>
   ```
2. Google Fonts are loaded explicitly (not relying on system fonts)
3. Consider disabling Rocket Loader entirely in Cloudflare > Speed > Optimization

### Web container unhealthy

Check the app logs:

```bash
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml logs web --tail 30"
```

Common causes:
- Missing secret file (check `/opt/zdenovo/secrets/` has all 4 files)
- Python import error (dependency issue — rebuild with `--no-cache`)
- Port conflict (another process on 8000)

### `git pull --ff-only` fails on server

The server branch has diverged. Never commit directly on the server. Fix:

```bash
ssh zdenovo "cd /opt/zdenovo && git reset --hard origin/main"
```

### Claude generation times out

The `/admin/*` and `/api/*` locations have `proxy_read_timeout 180s`. If Claude API takes
longer than 3 minutes:

1. Check the Anthropic API status
2. Increase timeout in nginx config on the server
3. Reload nginx: `docker compose -f docker-compose.prod.yml exec nginx nginx -s reload`

### System nginx conflicts with Docker nginx

Hetzner Ubuntu images ship with system nginx. If port 80 is already in use:

```bash
ssh zdenovo "systemctl stop nginx && systemctl disable nginx"
```

### SSH connection refused

1. Check the server IP in `~/.ssh/config` is correct
2. Verify SSH key permissions: `chmod 600 ~/.ssh/<key>` and `chmod 700 ~/.ssh`
3. Check UFW allows SSH: `ssh zdenovo "ufw status"` (if you can connect another way)
4. Use Hetzner console (web UI) as a fallback

---

## Make Targets Reference

### Local development

| Target | Purpose |
|--------|---------|
| `make dev` | Start dev stack on http://localhost:8080 |
| `make dev-logs` | Tail dev container logs |
| `make dev-down` | Stop and remove dev containers |
| `make test` | Run pytest with coverage |

### Production (run on server)

| Target | Purpose |
|--------|---------|
| `make prod` | Build and start production stack |
| `make prod-logs` | Tail production logs |
| `make prod-stop` | Stop containers (data preserved) |
| `make prod-down` | Remove containers (data preserved, volumes kept) |
| `make check` | Health check: HTTPS + redirect + API |
| `make cert-init` | Bootstrap Let's Encrypt certificate (first time) |
| `make cert-renew` | Force certificate renewal |

### Remote deployment (run locally, SSHes to server)

| Target | Purpose |
|--------|---------|
| `make deploy-first` | One-time server setup + first deploy |
| `make deploy` | Pull latest code + rebuild on server |
| `make deploy-restart` | Restart web container (picks up secret changes) |
| `make secret-set NAME=x VALUE=y` | Update a single secret and restart |
| `make backup` | Download blog.db from server |

---

## Environment Variables Reference

### Server `.env` (non-secret config only)

Only two variables live in the server's `.env`. Everything else is a secret file.

| Variable | Example | Used by |
|----------|---------|---------|
| `DOMAIN` | `zdenovo.com` | nginx config, health checks |
| `CERTBOT_EMAIL` | `you@example.com` | Let's Encrypt (if used) |

### Local `.env` (everything for dev convenience)

| Variable | Example | Purpose |
|----------|---------|---------|
| `DOMAIN` | `zdenovo.com` | Makefile targets |
| `CERTBOT_EMAIL` | `you@example.com` | Makefile targets |
| `SERVER_HOST` | `1.2.3.4` | `make deploy*` (SSH target) |
| `SERVER_USER` | `root` | `make deploy*` (SSH user) |
| `DEPLOY_DIR` | `/opt/zdenovo` | `make deploy*` (remote path) |
| `REPO_URL` | `https://github.com/user/repo.git` | `server-setup.sh` (first deploy only) |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Dev: env var. Prod: file secret |
| `UNSPLASH_ACCESS_KEY` | `your-key` | Dev: env var. Prod: file secret |
| `ADMIN_PASSWORD` | `strong-password` | Dev: env var. Prod: file secret |
| `SECRET_KEY` | `random-64-char-hex` | Dev: env var. Prod: file secret |

### Secret categories

| Secret | Runtime? | Dev source | Prod source |
|--------|----------|-----------|-------------|
| `anthropic_api_key` | Yes — Claude API calls | `.env` env var | `/run/secrets/anthropic_api_key` |
| `unsplash_access_key` | Yes — hero images | `.env` env var | `/run/secrets/unsplash_access_key` |
| `admin_password` | Yes — admin login | `.env` env var | `/run/secrets/admin_password` |
| `secret_key` | Yes — session cookies | `.env` env var | `/run/secrets/secret_key` |

---

## Production Hardening Checklist

- [ ] SSH config alias set up in `~/.ssh/config` (no hardcoded IPs in repo)
- [ ] No `.env` with secrets on the server — only `DOMAIN` + `CERTBOT_EMAIL`
- [ ] All API keys in `/opt/zdenovo/secrets/` with chmod 600
- [ ] `secrets/` directory is chmod 700, owned by root
- [ ] `ADMIN_PASSWORD` is strong (64+ character hex)
- [ ] `SECRET_KEY` is random 64-char hex (`python3 -c "import secrets; print(secrets.token_hex(32))"`)
- [ ] Cloudflare SSL set to Flexible, Always Use HTTPS enabled
- [ ] Cloudflare Rocket Loader disabled (or `data-cfasync="false"` on critical scripts)
- [ ] Rate limiting active on `/admin/login`, `/admin/*`, `/api/*`
- [ ] `proxy_read_timeout 180s` for admin and API (Claude generation takes 1-2 min)
- [ ] UFW active: only SSH (22), HTTP (80), HTTPS (443) open
- [ ] SSH key-only auth (consider disabling password login)
- [ ] System nginx stopped and disabled (`systemctl disable nginx`)
- [ ] `nginx/no-default.conf` mounted to prevent default server block
- [ ] `restart: unless-stopped` on all containers
- [ ] `secrets/` in `.gitignore`
- [ ] No PII (server IPs, SSH key names) in committed files
- [ ] Regular database backups (`make backup`)
