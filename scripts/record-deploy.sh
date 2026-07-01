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

if curl -sfk -X POST https://localhost/api/deploys \
    -H "Host: zdenovo.com" \
    -H "Content-Type: application/json" \
    -H "X-Deploy-Token: $DEPLOY_TOKEN" \
    --max-time 10 \
    -d "{\"commit_hash\":\"${COMMIT_HASH}\",\"status\":\"${STATUS}\",\"duration_s\":${DURATION_S},\"triggered_by\":\"makefile\",\"notes\":$([ -n "$NOTES" ] && echo "\"${NOTES}\"" || echo "null")}"; then
    echo "  ✓ Deploy event recorded (${STATUS})"
else
    echo "  ⚠ Deploy event recording failed (non-fatal)"
fi

exit 0
