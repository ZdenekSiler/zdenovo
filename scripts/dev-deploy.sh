#!/usr/bin/env bash
# =============================================================================
# dev-deploy.sh — local development deployment script
#
# PURPOSE
#   Start (or restart) the local dev environment from scratch. Use this
#   instead of `make dev` when `make` is not available, or as a self-
#   contained reference for what the dev stack does.
#
# WHAT IT DOES (in order)
#   1. Checks prerequisites (Docker running, .env present)
#   2. Optionally runs the test suite (skip with --no-test)
#   3. Stops any existing dev containers
#   4. Builds the Docker image and starts the container
#   5. Waits for the app to respond on :8080
#   6. Prints a health check summary and the local URL
#
# USAGE
#   ./scripts/dev-deploy.sh           # full flow (tests + build + start)
#   ./scripts/dev-deploy.sh --no-test # skip tests, just build + start
#   ./scripts/dev-deploy.sh --restart # tear down first, then full flow
#
# HOW THE DEV STACK WORKS
#   - docker-compose.yml defines a single "web" service
#   - Builds from the root Dockerfile (FastAPI + Jinja2 + SQLite)
#   - Container port 8000 → host port 8080
#   - ./data/ is mounted as /data inside the container (SQLite lives here)
#   - ./.env is bind-mounted read-only as /app/backend/.env
#   - The app auto-migrates the DB schema on startup (backend/db.py)
#
# PREREQUISITES
#   - Docker Desktop (or Docker Engine) must be running
#   - .env file must exist (copy from .env.example and fill in values)
#   - uv must be installed (only needed if --no-test is NOT set)
#
# DEV VS PROD
#   Dev  (this script / make dev):   single container, no nginx, no SSL,
#                                     hot-reloadable via volume mounts
#   Prod (make deploy / make prod):  nginx + certbot + SSL, Hetzner VPS,
#                                     git pull then docker compose build
#
# =============================================================================

set -euo pipefail

# ── parse flags ──────────────────────────────────────────────────────────────

RUN_TESTS=true
RESTART=false

for arg in "$@"; do
  case "$arg" in
    --no-test) RUN_TESTS=false ;;
    --restart) RESTART=true ;;
    --help|-h)
      sed -n '/^# PURPOSE/,/^# ===/p' "$0" | head -n -1 | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown flag: $arg (use --no-test, --restart, or --help)" && exit 1 ;;
  esac
done

# ── helpers ──────────────────────────────────────────────────────────────────

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

step()  { echo -e "${CYAN}→${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
fail()  { echo -e "${RED}✗${NC} $*"; exit 1; }

# ── cd to repo root ──────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo ""
echo "  zdenovo dev deployment"
echo "  repo: $REPO_ROOT"
echo "  branch: $(git branch --show-current 2>/dev/null || echo 'unknown')"
echo ""

# ── step 1: prerequisites ────────────────────────────────────────────────────

step "Checking prerequisites..."

if ! docker info &>/dev/null; then
  fail "Docker is not running. Start Docker Desktop and retry."
fi
ok "Docker is running"

if [[ ! -f .env ]]; then
  fail ".env not found — copy .env.example → .env and fill in values."
fi
ok ".env found"

# ── step 2: tests (optional) ─────────────────────────────────────────────────

if $RUN_TESTS; then
  step "Running test suite (skip with --no-test)..."
  if ! command -v uv &>/dev/null; then
    warn "uv not found — skipping tests. Install from https://docs.astral.sh/uv/"
  else
    # Exclude e2e tests (Playwright needs a live server on :8000, which isn't up yet)
    cd backend
    uv run pytest -q --ignore=tests/test_e2e.py 2>&1 | tail -5
    cd ..
    ok "Tests passed"
  fi
else
  warn "Skipping tests (--no-test)"
fi

# ── step 3: stop existing containers ─────────────────────────────────────────

if $RESTART; then
  step "Tearing down existing containers (--restart)..."
  docker compose down --remove-orphans 2>/dev/null || true
  ok "Containers removed"
else
  step "Stopping existing dev containers (if any)..."
  docker compose stop 2>/dev/null || true
fi

# ── step 4: build and start ───────────────────────────────────────────────────
#
#   docker compose up --build:
#     - Rebuilds the image from the Dockerfile (picks up any code changes)
#     - Starts the "web" service (FastAPI via uvicorn on container :8000)
#     - -d runs detached (background)
#
#   The Dockerfile does:
#     1. Install uv + Python deps from pyproject.toml
#     2. Copy backend/ and frontend/ into the image
#     3. CMD: uv run uvicorn main:app --host 0.0.0.0 --port 8000
#
#   DB migration happens automatically on first request (backend/db.py
#   calls ensure_schema() which ALTERs tables and creates new ones).

step "Ensuring required Docker networks exist..."
docker network inspect zdenovo_public &>/dev/null || docker network create zdenovo_public
ok "Networks ready"

step "Building image and starting container..."
docker compose up --build -d

ok "Container started"

# ── step 5: health check (wait for app to respond) ───────────────────────────

step "Waiting for app to respond on http://localhost:8080 ..."

MAX_WAIT=30
elapsed=0
until curl -sf -o /dev/null http://localhost:8080/ 2>/dev/null; do
  if (( elapsed >= MAX_WAIT )); then
    fail "App did not respond within ${MAX_WAIT}s. Check logs:\n  docker compose logs web"
  fi
  sleep 2
  (( elapsed += 2 ))
done

ok "App is responding (${elapsed}s)"

# ── step 6: summary ──────────────────────────────────────────────────────────

echo ""
echo "  ─────────────────────────────────────────────"
echo "  Local dev environment is running"
echo ""
echo "  URL        http://localhost:8080"
echo "  Admin      http://localhost:8080/admin"
echo "  API docs   http://localhost:8080/docs"
echo ""
echo "  Logs       docker compose logs -f web"
echo "  Stop       docker compose down"
echo "  ─────────────────────────────────────────────"
echo ""
