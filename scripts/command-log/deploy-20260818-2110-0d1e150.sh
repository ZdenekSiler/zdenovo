#!/usr/bin/env bash
#
# deploy-20260818-2110-0d1e150.sh — replay + audit trail for ONE prod deploy.
#
#   Deployed HEAD : 0d1e150  docs(skills): correct gen skills and spec link validation
#                   1589181  feat(scripts): carry the series row in draft-to-prod
#                   26b8399  fix(prompts): stop the sources step from inventing URLs
#   When (UTC)    : 2026-08-18 21:10
#   Triggered by  : /deploy prod ("deploy to prod")
#   Result        : success (21s build, web container healthy); HTTP 200 / 41 posts; BUILD_COMMIT 0d1e150
#   Nature        : BEHAVIOUR CHANGE (generation only) + repo-only tooling.
#                   26b8399 edits data/prompts/, which the running app reads at generation time —
#                   the sources step now allows 0-5 sources (was: required 3) and demands verbatim
#                   URLs. No route, template, or schema changed, so reader-facing pages are untouched.
#                   1589181/0d1e150 are scripts, skills and a spec — not part of the FastAPI app.
#   Notes         : auto DB backup taken by make prod; nginx pre-existing "(unhealthy)" state, unrelated
#                   (same as the 2026-07-22 deploy). Dev was deployed and health-checked first;
#                   its 30s health-check timeout was Playwright installing at container start, not a fault.
#
#   NOT in this deploy: the source-link-validation feature itself. Only its spec
#   (docs/specs/source-link-validation.md) shipped; link_validator.py and the admin
#   endpoint are unimplemented.
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
  ./scripts/dev-deploy.sh                                                        # dev rebuilt + health-checked first
  git commit -m "fix(prompts): stop the sources step from inventing URLs"        # 26b8399
  git commit -m "feat(scripts): carry the series row in draft-to-prod"           # 1589181
  git commit -m "docs(skills): correct gen skills and spec link validation"      # 0d1e150
  git push origin main                                                           # fast gate PASS → bfbfd06..0d1e150
                                                                                 #   unit tests PASS, bandit clean,
                                                                                 #   pip-audit, 33/33 routes protected
HIST

step "⚠️ PROD DEPLOY — pull + rebuild + recreate web (auto DB backup + health check):"
maybe "ssh $SSH_ALIAS \"cd $REMOTE_DIR && git pull --ff-only && make prod\""

step "Verify — site live (read-only):"
maybe "python3 -c \"import urllib.request,json;r=urllib.request.urlopen(urllib.request.Request('https://zdenovo.com/api/posts',headers={'User-Agent':'Mozilla/5.0'}),timeout=15);print('verify:',r.status,len(json.loads(r.read())),'posts')\""

step "Verify — the changed prompt files are in the running image (⚠️ read-only exec):"
maybe "ssh $SSH_ALIAS \"cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml exec -T web python3 -c \\\"import json;print('minItems:',json.load(open('/app/backend/data/prompts/sources_tool.json'))['input_schema']['properties']['sources']['minItems'])\\\"\""

step "Verify — prod HEAD matches (read-only):"
maybe "ssh $SSH_ALIAS \"cd $REMOTE_DIR && git rev-parse --short HEAD\""

step "Rollback if needed:"
printf '  \033[2m$ ssh %s "cd %s && git revert HEAD --no-edit && make prod"\033[0m\n' "$SSH_ALIAS" "$REMOTE_DIR"
