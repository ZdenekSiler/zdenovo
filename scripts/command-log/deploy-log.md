# Prod Deploy Audit Trail

Human-readable, append-only log of every production deploy (newest first). Complements the
JSON deploy-event `make prod` records in the DB. One entry per prod deploy, written per the
command-log rules in `.claude/rules/debugging.md`: exact commands in order, prod-mutating steps
flagged ⚠️, secrets redacted. This file is **tracked in git** (it is not a `session-*` file).

---

## 2026-07-22 08:57 UTC — `3f2b437` — success

**Deployed HEAD:** `3f2b437` — chore(scripts): track dev→prod draft tooling, ignore per-session logs
**Feature in this push:** `9ab78ae` — feat(drafts): unique hero images + admin image picker in review
**Triggered by:** `/deploy prod` (commit push deploy) · **Result:** success (~20s build), web container healthy

Commands run (⚠️ = prod-mutating; secrets redacted):

1. `git add <feature files>` → `git commit` — feature commit `9ab78ae` — OK
2. `git add .gitignore scripts/… docs/playbooks/…` → `git commit` — tooling commit `3f2b437` — OK
3. `git push origin main` — pre-push gate (unit tests + route-auth audit: 33/33 protected) — **PASS**, `2b02ea9..3f2b437`
4. ⚠️ `ssh zdenovo "cd /opt/zdenovo && git pull --ff-only && make prod"` — pull + Docker rebuild + recreate `web` — **healthy**; auto DB backup taken; deploy-event recorded `success`
5. Verify (read-only): `GET https://zdenovo.com/api/posts` → **HTTP 200, 25 posts**
6. ⚠️(read-only) `ssh zdenovo … docker compose … exec -T web cat /app/BUILD_COMMIT` → `3f2b437` (matches pushed HEAD)

**Notes:** nginx reported `(unhealthy)` but that is a pre-existing state ("Up 3 weeks"), unrelated
to this deploy; web container healthy and routing verified. Live browser click-through of the new
image picker not yet exercised (endpoints + template render are test-covered).
