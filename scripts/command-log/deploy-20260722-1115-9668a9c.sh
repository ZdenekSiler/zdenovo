#!/usr/bin/env bash
#
# deploy-20260722-1115-9668a9c.sh — replay + audit trail for ONE prod deploy.
#
#   Deployed HEAD : 9668a9c  feat(skills): add /draft-to-prod to copy a dev draft into the prod queue
#   When (UTC)    : 2026-07-22 11:15
#   Triggered by  : /deploy prod  ("commit push deploy")
#   Result        : success (~14s build, web container healthy); HTTP 200 / 25 posts; BUILD_COMMIT 9668a9c
#   Nature        : MARKER-ONLY — the commit adds a Claude Code skill (.claude/skills/draft-to-prod),
#                   which is not part of the running FastAPI app; site behavior unchanged, BUILD_COMMIT bumped.
#   Notes         : auto DB backup taken by make prod; nginx pre-existing "(unhealthy)" state, unrelated.
#
# Runnable: PREVIEW by default (prints, runs nothing). EXECUTE=1 re-runs the deploy (idempotent).
#
set -euo pipefail
SSH_ALIAS="${SSH_ALIAS:-zdenovo}"
REMOTE_DIR="${REMOTE_DIR:-/opt/zdenovo}"
EXECUTE="${EXECUTE:-0}"

step()  { printf '\n\033[1;35m▶ %s\033[0m\n' "$*"; }
maybe() { printf '  \033[2m$ %s\033[0m\n' "$1"; [ "$EXECUTE" = 1 ] && eval "$1" || printf '  \033[2m(preview — set EXECUTE=1 to run)\033[0m\n'; }

step "Historical — already done for this deploy (not re-runnable):"
cat <<'HIST'
  git commit -m "feat(skills): add /draft-to-prod to copy a dev draft into the prod queue"   # 9668a9c
  git push origin main                                                                        # gate PASS → 3fd522b..9668a9c
HIST

step "⚠️ PROD DEPLOY — pull + rebuild + recreate web (auto DB backup + health check):"
maybe "ssh $SSH_ALIAS \"cd $REMOTE_DIR && git pull --ff-only && make prod\""

step "Verify — site live (read-only):"
maybe "python3 -c \"import urllib.request,json;r=urllib.request.urlopen(urllib.request.Request('https://zdenovo.com/api/posts',headers={'User-Agent':'Mozilla/5.0'}),timeout=15);print('verify:',r.status,len(json.loads(r.read())),'posts')\""

step "Verify — prod BUILD_COMMIT matches (⚠️ read-only exec):"
maybe "ssh $SSH_ALIAS \"cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml exec -T web cat /app/BUILD_COMMIT\""

step "Rollback if needed:"
printf '  \033[2m$ ssh %s "cd %s && git revert HEAD --no-edit && make prod"\033[0m\n' "$SSH_ALIAS" "$REMOTE_DIR"
