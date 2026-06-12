# Deployment Guide

## Deployment Models

Choose based on traffic, cost tolerance, and operational complexity.

| Model | Best for | Cost | Complexity |
|-------|----------|------|------------|
| [Docker Compose](#docker-compose) | Local / VPS, self-contained image | $4–6/mo VPS | Low |
| [VPS / bare metal](#vps--bare-metal) | Full control, SQLite persistence | $4–6/mo | Low |
| [PaaS (Railway, Render)](#paas) | Zero-ops, fast deploys | $0–7/mo | Very low |
| [Serverless (no SQLite)](#serverless-note) | Spike traffic, no state | $0–5/mo | Medium |
| [Fly.io + volume](#flyio) | Low-cost, persistent disk, global | $0–5/mo | Low |

**Recommended for this app**: Docker Compose on a VPS (simplest, fully reproducible) or Fly.io (free tier with SQLite persistence).

---

## Docker Compose

The repo ships with a `Dockerfile` and `docker-compose.yml` at the project root.

### Prerequisites

- [Docker Desktop](https://docs.docker.com/get-docker/) (includes Compose) — or Docker Engine + Compose plugin on Linux/WSL

### Local development

```bash
# Build image and start container (foreground)
docker compose up --build

# Rebuild after code changes
docker compose up --build

# Run in background
docker compose up -d

# Follow logs
docker compose logs -f

# Stop and remove containers (data volume is preserved)
docker compose down

# Stop and remove containers AND the SQLite data volume
docker compose down -v
```

App is served at **http://localhost:8080** (mapped from container port 8000).

SQLite data is stored in the named Docker volume `db_data`, mounted at `/data` inside the container. The volume persists across restarts and rebuilds — `docker compose down -v` is the only command that removes it.

### Deploy to a VPS with Docker

```bash
# On the server — install Docker
curl -fsSL https://get.docker.com | sh

# Clone repo
git clone <repo-url> /opt/zdenovo
cd /opt/zdenovo

# Start (detached)
docker compose up -d --build

# View logs
docker compose logs -f
```

To update after a code push:

```bash
cd /opt/zdenovo
git pull
docker compose up -d --build
```

### Running tests inside Docker

Tests are excluded from the image via `.dockerignore`. Run them directly in WSL/Linux:

```bash
cd backend
uv run pytest --cov --cov-report=term-missing
```

### Build the image without Compose

```bash
docker build -t zdenovo .
docker run -p 8080:8000 -e DB_DIR=/data -v zdenovo_data:/data zdenovo
```

---

## VPS / Bare Metal

Providers: Hetzner (cheapest), DigitalOcean, Linode.

### Hetzner CX22 — ~€4/mo

```bash
# On the server
sudo apt update && sudo apt install -y python3.12 curl

# Install uv
curl -fsSL https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Clone and install
git clone <repo-url> /opt/zdenovo
cd /opt/zdenovo/backend
uv sync --no-dev

# Run with uvicorn behind nginx
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

### systemd service

Create `/etc/systemd/system/zdenovo.service`:

```ini
[Unit]
Description=zdenovo FastAPI app
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/zdenovo/backend
ExecStart=/root/.local/bin/uv run uvicorn main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now zdenovo
```

### Nginx reverse proxy

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Add HTTPS with: `sudo apt install certbot python3-certbot-nginx && sudo certbot --nginx`

---

## PaaS

### Railway — free tier available

1. Push repo to GitHub
2. Create new project → Deploy from GitHub
3. Set **root directory** to `backend/`
4. Set start command: `uv run uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add env var: `PORT=8000`

**SQLite caveat**: Railway's filesystem is ephemeral. The DB resets on redeploy. For a portfolio/blog with infrequent writes, seed data in `db.py` handles this. For persistence, mount a volume (Railway Pro) or switch to a free Postgres tier.

### Render — free tier (spins down after 15 min idle)

1. New Web Service → Connect GitHub repo
2. Root directory: `backend`
3. Build command: `uv sync --no-dev`
4. Start command: `uv run uvicorn main:app --host 0.0.0.0 --port $PORT`

Free tier has cold starts (~30s). Upgrade to $7/mo Starter to avoid spin-down.

---

## Fly.io

Best balance of cost and SQLite persistence via volumes.

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Authenticate
fly auth login

# From the project root (Dockerfile is at root)
fly launch --name zdenovo --region fra --no-deploy
```

Create a volume for SQLite persistence:

```bash
fly volumes create zdenovo_data --size 1 --region fra
```

Add to `fly.toml`:

```toml
[mounts]
  source = "zdenovo_data"
  destination = "/data"
```

Update `backend/db.py` to use the mounted path in production:

```python
import os
DB_PATH = Path(os.getenv("DB_DIR", Path(__file__).parent)) / "blog.db"
```

Deploy:

```bash
fly deploy
```

**Cost**: ~$0/mo on free tier (3 shared-cpu-1x VMs free), volume ~$0.15/GB/mo.

---

## Serverless Note

SQLite is a local file — it doesn't work on stateless serverless platforms (Vercel, AWS Lambda, Cloudflare Workers) without an external database. Options if you want serverless:

- Replace SQLite with **Turso** (SQLite over HTTP, generous free tier)
- Replace SQLite with **Neon** (serverless Postgres, free tier)
- Keep SQLite but treat the DB as read-only (seed at deploy time, no writes)

---

## Lowest-Cost Path

```
Free:     Fly.io free tier + 1 GB volume ≈ $0.15/mo
Budget:   Hetzner CX22 (€4/mo) — most control
No-ops:   Railway free tier — redeploys reset DB (fine for seed data)
```

For a portfolio site with occasional blog writes via the `/api/posts` endpoint, **Railway free tier** is the fastest to set up. For SQLite persistence, **Fly.io with a volume** is the best value.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_DIR` | `backend/` | Directory for `blog.db` |
| `PORT` | `8000` | Port for uvicorn (set automatically by PaaS) |

Set in platform dashboard or `.env` file (gitignored).
