#!/bin/bash
# Record a deploy event to the local FastAPI. Always exits 0 — non-fatal.
# Usage: record-deploy.sh <commit_hash> <status> <duration_s>
COMMIT_HASH="${1}"
STATUS="${2}"
DURATION_S="${3:-0}"
NOTES="${4:-}"
TOKEN_PATH="${TOKEN_PATH:-/opt/zdenovo/secrets/deploy_token}"

if [ -z "$COMMIT_HASH" ] || [ -z "$STATUS" ]; then
    echo "  ⚠ record-deploy.sh: missing arguments — skipping deploy record"
    exit 0
fi

DEPLOY_TOKEN=$(cat "$TOKEN_PATH" 2>/dev/null || true)

if [ -z "$DEPLOY_TOKEN" ]; then
    echo "  ⚠ deploy_token not found at $TOKEN_PATH — skipping deploy record"
    exit 0
fi

BODY=$(python3 -c '
import json, sys
commit_hash, status, duration_s, notes = sys.argv[1:5]
print(json.dumps({
    "commit_hash": commit_hash,
    "status": status,
    "duration_s": int(duration_s),
    "triggered_by": "makefile",
    "notes": notes or None,
}))
' "$COMMIT_HASH" "$STATUS" "$DURATION_S" "$NOTES")

if curl -sfk -X POST https://localhost/api/deploys \
    -H "Host: zdenovo.com" \
    -H "Content-Type: application/json" \
    -H "X-Deploy-Token: $DEPLOY_TOKEN" \
    --max-time 10 \
    -d "$BODY"; then
    echo "  ✓ Deploy event recorded (${STATUS})"
else
    echo "  ⚠ Deploy event recording failed (non-fatal)"
fi

exit 0
