#!/usr/bin/env bash
#
# deploy-20260722-0857-3f2b437.sh — replay + audit trail for ONE prod deploy.
# (One standalone file per deploy; name = deploy-<UTCdate>-<UTChhmm>-<shortcommit>.sh)
#
#   Deployed HEAD : 3f2b437  chore(scripts): track dev→prod draft tooling, ignore per-session logs
#   Feature       : 9ab78ae  feat(drafts): unique hero images + admin image picker in review
#   When (UTC)    : 2026-07-22 08:57
#   Triggered by  : /deploy prod  ("commit push deploy")
#   Result        : success (~20s build, web container healthy); HTTP 200 / 25 posts; BUILD_COMMIT 3f2b437
#   Notes         : auto DB backup taken by make prod; nginx pre-existing "(unhealthy)" state, unrelated.
#
# Runnable: PREVIEW by default (prints commands, runs nothing). EXECUTE=1 re-runs the deploy
# (idempotent — pulls + rebuilds the same commit). Secrets are never echoed.
#
set -euo pipefail
SSH_ALIAS="${SSH_ALIAS:-zdenovo}"
REMOTE_DIR="${REMOTE_DIR:-/opt/zdenovo}"
EXECUTE="${EXECUTE:-0}"

step()  { printf '\n\033[1;35m▶ %s\033[0m\n' "$*"; }
maybe() { printf '  \033[2m$ %s\033[0m\n' "$1"; [ "$EXECUTE" = 1 ] && eval "$1" || printf '  \033[2m(preview — set EXECUTE=1 to run)\033[0m\n'; }

step "Historical — already done for this deploy (not re-runnable):"
cat <<'HIST'
  git commit -m "feat(drafts): unique hero images + admin image picker in review"        # 9ab78ae
  git commit -m "chore(scripts): track dev→prod draft tooling, ignore per-session logs"   # 3f2b437
  git push origin main                                                                     # gate PASS → 2b02ea9..3f2b437
HIST

step "⚠️ PROD DEPLOY — pull + rebuild + recreate web (auto DB backup + health check):"
maybe "ssh $SSH_ALIAS \"cd $REMOTE_DIR && git pull --ff-only && make prod\""

step "Verify — site live (read-only):"
maybe "python3 -c \"import urllib.request,json;r=urllib.request.urlopen(urllib.request.Request('https://zdenovo.com/api/posts',headers={'User-Agent':'Mozilla/5.0'}),timeout=15);print('verify:',r.status,len(json.loads(r.read())),'posts')\""

step "Verify — prod BUILD_COMMIT matches (⚠️ read-only exec):"
maybe "ssh $SSH_ALIAS \"cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml exec -T web cat /app/BUILD_COMMIT\""

step "Rollback if needed:"
printf '  \033[2m$ ssh %s "cd %s && git revert HEAD --no-edit && make prod"\033[0m\n' "$SSH_ALIAS" "$REMOTE_DIR"
