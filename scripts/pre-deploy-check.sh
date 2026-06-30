#!/usr/bin/env bash
# Pre-deploy security/sanity check — run on the SERVER before `make prod` builds.
# Verifies secrets, git state, disk space, and Docker before touching containers.
set -euo pipefail

SECRETS_DIR="${SECRETS_DIR:-$(dirname "$0")/../secrets}"
SECRETS_DIR="$(cd "$SECRETS_DIR" && pwd)"

PASS=0
FAIL=0

check() {
  local label="$1"
  local ok="$2"  # "true" or "false"
  local detail="${3:-}"
  if [[ "$ok" == "true" ]]; then
    echo "  ✓ $label"
    ((PASS++)) || true
  else
    echo "  ✗ $label${detail:+: $detail}"
    ((FAIL++)) || true
  fi
}

# --- Secrets ---
echo "→ Checking secrets..."
for secret in secret_key admin_password anthropic_api_key cloudflare_api_token unsplash_access_key; do
  f="$SECRETS_DIR/$secret"
  if [[ -f "$f" ]] && [[ -s "$f" ]]; then
    check "$secret" "true"
  else
    check "$secret" "false" "missing or empty at $f"
  fi
done

# --- Git ---
echo "→ Checking git state..."
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
if [[ "$branch" == "main" ]]; then
  check "on main branch" "true"
else
  check "on main branch" "false" "currently on '$branch'"
fi

if git diff --name-only --diff-filter=U 2>/dev/null | grep -q .; then
  check "no merge conflicts" "false" "unresolved conflicts present"
else
  check "no merge conflicts" "true"
fi

# --- Disk ---
echo "→ Checking disk space..."
free_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
if (( free_kb >= 2 * 1024 * 1024 )); then
  check "at least 2GB free disk space" "true"
else
  check "at least 2GB free disk space" "false" "only $(( free_kb / 1024 ))MB free"
fi

# --- Docker ---
echo "→ Checking Docker..."
if docker info >/dev/null 2>&1; then
  check "Docker daemon running" "true"
else
  check "Docker daemon running" "false" "docker info failed — is the daemon up?"
fi

# --- Result ---
echo ""
if [[ $FAIL -gt 0 ]]; then
  echo "PRE-DEPLOY CHECK FAILED: $FAIL check(s) failed, $PASS passed."
  exit 1
else
  echo "PRE-DEPLOY CHECK PASSED: $PASS checks passed."
  exit 0
fi
