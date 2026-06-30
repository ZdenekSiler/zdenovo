#!/usr/bin/env bash
# Pre-deploy database backup. Runs on the server before each `make prod`.
# Copies blog.db from the Docker volume to /opt/zdenovo/backups/ with a timestamp.
set -euo pipefail

BACKUP_DIR="/opt/zdenovo/backups"
TIMESTAMP=$(date -u +"%Y%m%d-%H%M%S")
BACKUP_FILE="$BACKUP_DIR/blog-$TIMESTAMP.db"

mkdir -p "$BACKUP_DIR"

# Check if the web container is running and has the database
CONTAINER=$(docker ps --filter "name=zdenovo-web" --format "{{.Names}}" | head -1)

if [[ -z "$CONTAINER" ]]; then
  echo "  → No running web container — skipping DB backup (first deploy?)"
  exit 0
fi

docker cp "$CONTAINER:/data/blog.db" "$BACKUP_FILE"
echo "  ✓ DB backed up to $BACKUP_FILE"

# Keep only the last 10 backups
ls -t "$BACKUP_DIR"/blog-*.db 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
