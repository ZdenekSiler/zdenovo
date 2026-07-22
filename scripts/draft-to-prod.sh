#!/usr/bin/env bash
#
# draft-to-prod.sh — copy a generated draft (and/or fix its hero image) from DEV to PROD.
#
# WHY THIS EXISTS
#   A draft is a *row in the drafts table*, not a file in git. So `make prod` (which does
#   `git pull && rebuild`) never carries a draft across. The prod DB lives inside a Docker
#   named volume (db_data:/data), unreachable from the host filesystem — the only way in is
#   `docker compose ... cp` (files) and `docker compose ... exec` (run code against the DB).
#   This script wraps that flow so the exact reviewed draft moves over byte-for-byte, with a
#   DB backup taken before every write.
#
# SUBCOMMANDS
#   generate  "<description>" [tag1,tag2]   Generate a draft on dev via the authed API (calls Claude)
#   copy      <draft_id>                    Copy that draft row from dev DB -> prod DB
#   set-image <draft_id> "<query>" [id]     Swap the hero image (dev + prod) to an Unsplash pick
#
# EVERY command is echoed before it runs. PROD/DEV writes are flagged. Secrets are read from
# .env into shell vars and never printed (login shows `password=<redacted>`).
#
# ENV KNOBS (all have sane defaults)
#   DEBUG=1     `set -x` full shell trace          DRY_RUN=1  echo commands, run nothing mutating
#   SSH_ALIAS=zdenovo   REMOTE_DIR=/opt/zdenovo   COMPOSE=docker-compose.prod.yml   SERVICE=web
#   DEV_URL=http://localhost:8080   DEV_DB=./data/blog.db   ENV_FILE=.env
#
# EXAMPLES
#   ./scripts/draft-to-prod.sh generate "Qwen3.8 Max vs closed frontier models" ai,llm
#   ./scripts/draft-to-prod.sh copy d465bcb5-e6f2-4cb9-8890-685055182f53
#   DRY_RUN=1 ./scripts/draft-to-prod.sh set-image d465bcb5-... "server room data center" 2JJ3wBHu4_0
#
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────────
DEV_URL="${DEV_URL:-http://localhost:8080}"
SSH_ALIAS="${SSH_ALIAS:-zdenovo}"
REMOTE_DIR="${REMOTE_DIR:-/opt/zdenovo}"
COMPOSE="${COMPOSE:-docker-compose.prod.yml}"
SERVICE="${SERVICE:-web}"
ENV_FILE="${ENV_FILE:-.env}"
DEV_DB="${DEV_DB:-./data/blog.db}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/lib"
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
[ "${DEBUG:-0}" = "1" ] && set -x

# ── Pretty logging ──────────────────────────────────────────────────────────────
step() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
info() { printf '  \033[2m%s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m⚠ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── Secret loader — sets global SECRET, prints nothing ──────────────────────────
load_secret() {
  local name="$1"
  SECRET="$(grep -E "^${name}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- \
            | sed 's/^["'"'"']//; s/["'"'"']$//')"
  [ -n "${SECRET:-}" ] || die "$name not found in $ENV_FILE"
}

# ── Remote helper — run a command on the prod host (echoes it first) ────────────
remote() {
  info "\$ ssh $SSH_ALIAS \"cd $REMOTE_DIR && $*\""
  [ "${DRY_RUN:-0}" = "1" ] && { info "(dry-run: not executed)"; return 0; }
  ssh "$SSH_ALIAS" "cd '$REMOTE_DIR' && $*"
}

# ── Push a local file INTO the prod container: scp to host /tmp, then docker cp ──
push_into_container() {
  local local_file="$1" container_path="$2" base
  base="$(basename "$local_file")"
  info "\$ scp $local_file $SSH_ALIAS:/tmp/$base"
  [ "${DRY_RUN:-0}" = "1" ] || scp -q "$local_file" "$SSH_ALIAS:/tmp/$base"
  remote "docker compose -f '$COMPOSE' cp '/tmp/$base' '$SERVICE:$container_path'"
}

# ── Run a python helper against the DB INSIDE the container ─────────────────────
exec_in_container() {  # exec_in_container <script_basename> <args...>
  remote "docker compose -f '$COMPOSE' exec -T '$SERVICE' python3 /tmp/$*"
}

# ── Subcommand: generate ────────────────────────────────────────────────────────
cmd_generate() {
  local desc="${1:?usage: generate \"<description>\" [tag1,tag2]}" tags_csv="${2:-}"
  local jar="$SCRATCH/cookies.txt" out="$SCRATCH/draft.json"

  step "1/2  Log in to dev admin (session cookie -> $jar)"
  load_secret ADMIN_PASSWORD
  info "\$ curl -c \$jar -X POST $DEV_URL/admin/login  (password=<redacted>)"
  curl -s -o /dev/null -c "$jar" -X POST "$DEV_URL/admin/login" \
    --data-urlencode "password=$SECRET" --data-urlencode "next=/admin/posts"
  [ "$(curl -s -o /dev/null -w '%{http_code}' -b "$jar" "$DEV_URL/admin/posts")" = "200" ] \
    || die "login failed (check ADMIN_PASSWORD)"
  info "session OK"

  step "2/2  POST /api/posts/generate  (authed; this calls Claude, ~1-2 min)"
  local body
  body="$(python3 -c 'import json,sys; print(json.dumps({"description":sys.argv[1],"tags":[t for t in sys.argv[2].split(",") if t]}))' "$desc" "$tags_csv")"
  info "\$ curl -b \$jar -X POST $DEV_URL/api/posts/generate -d <json>"
  curl -s -b "$jar" -o "$out" -w "  HTTP %{http_code} in %{time_total}s\n" \
    -X POST "$DEV_URL/api/posts/generate" \
    -H "Content-Type: application/json" -d "$body"
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("  id:   ",d["id"]); print("  title:",d["title"]); print("  score:",d.get("quality_score"))' "$out"
  info "next: ./scripts/draft-to-prod.sh copy <id>"
}

# ── Subcommand: copy ────────────────────────────────────────────────────────────
cmd_copy() {
  local id="${1:?usage: copy <draft_id>}"

  step "1/3  Export draft $id from the dev DB (read-only)"
  info "\$ python3 lib/export_draft.py $DEV_DB $id row.json"
  python3 "$LIB/export_draft.py" "$DEV_DB" "$id" "$SCRATCH/row.json"

  step "2/3  Ship the row + loader into the prod container"
  push_into_container "$SCRATCH/row.json" "/tmp/row.json"
  push_into_container "$LIB/insert_draft.py" "/tmp/insert_draft.py"

  warn "3/3  PROD-MUTATION: back up blog.db, then INSERT the draft row"
  exec_in_container "insert_draft.py /tmp/row.json"
}

# ── Subcommand: set-image ───────────────────────────────────────────────────────
cmd_set_image() {
  local id="${1:?usage: set-image <draft_id> \"<query>\" [photo_id]}"
  local query="${2:?need an Unsplash query}" photo_id="${3:-}"

  step "1/3  Resolve an Unsplash hero URL (dev-side)"
  load_secret UNSPLASH_ACCESS_KEY
  info "\$ UNSPLASH_ACCESS_KEY=<redacted> python3 lib/fetch_unsplash.py \"$query\" $photo_id"
  local url
  url="$(UNSPLASH_ACCESS_KEY="$SECRET" python3 "$LIB/fetch_unsplash.py" "$query" $photo_id)"
  printf '%s\n' "$url" > "$SCRATCH/image.txt"
  info "url: ${url:0:70}..."

  warn "2/3  DEV-MUTATION: back up dev blog.db, then UPDATE image"
  info "\$ DB_DIR=$(dirname "$DEV_DB") python3 lib/update_draft_image.py $id image.txt"
  if [ "${DRY_RUN:-0}" != "1" ]; then
    DB_DIR="$(dirname "$DEV_DB")" python3 "$LIB/update_draft_image.py" "$id" "$SCRATCH/image.txt"
  else info "(dry-run: not executed)"; fi

  step "3/3  Same update on prod"
  push_into_container "$LIB/update_draft_image.py" "/tmp/update_draft_image.py"
  push_into_container "$SCRATCH/image.txt" "/tmp/image.txt"
  warn "PROD-MUTATION: back up blog.db, then UPDATE image"
  exec_in_container "update_draft_image.py '$id' /tmp/image.txt"
}

# ── Dispatch ────────────────────────────────────────────────────────────────────
sub="${1:-}"; shift || true
case "$sub" in
  generate)  cmd_generate "$@" ;;
  copy)      cmd_copy "$@" ;;
  set-image) cmd_set_image "$@" ;;
  *) die "usage: $0 {generate|copy|set-image} ...  (see the header comment for details)" ;;
esac
