#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Deploy replay — Terraform Quiz project page + terraform-quiz.zdenovo.com
#
#   Deployed commit : 993194e  fix(deploy): make certbot one-shot targets actually run certbot
#   Also shipped    : ec31fd2  fix(deps): patch mistune and pip advisories blocking pre-push audit
#                     b6b1766  feat(projects): add Terraform Quiz project page and subdomain
#   UTC timestamp   : 2026-09-03T19:20:58Z
#   Trigger         : user request — publish the Terraform Associate (004) quiz app
#   Result          : SUCCESS. make prod 21s. Cert issued (expires 2026-12-02).
#                     zdenovo.com/projects/terraform-quiz 200,
#                     terraform-quiz.zdenovo.com 200 (106021B), fakturant unaffected.
#                     prod BUILD_COMMIT=993194e
#
# NOTES / INCIDENTS
#   1. First cert-init attempt HUNG and was killed. Root cause: the certbot
#      service's compose `entrypoint` is the 12h renewal loop; `docker compose
#      run` overrides the COMMAND, not the ENTRYPOINT, so `certonly ...` was
#      appended as ignored positional args to `/bin/sh -c '<loop>'`. The
#      container ran a renew pass then sat in `sleep 12h`, logging nothing.
#      Fixed in 993194e by adding `--entrypoint certbot` to all four one-shot
#      invocations (cert-init, cert-renew, cert-init-fakturant,
#      cert-init-terraform-quiz). cert-init-fakturant had the same latent bug.
#      No damage: the kill happened before _gen-nginx-conf, so nginx/app.conf
#      was untouched and the site served 200s throughout.
#   2. Pre-push pip-audit blocked the push on two PRE-EXISTING advisories:
#      mistune 3.3.2 (CVE-2026-76098) and pip 26.1.2 (PYSEC-2026-3721).
#      Fixed in ec31fd2. pip needed declaring in the dev group because uv
#      reseeds its own pip into the venv on every `uv run`.
#   3. zdenovo-nginx-1 reports "unhealthy" — PRE-EXISTING, not caused here.
#      Its healthcheck runs busybox `wget http://localhost:80/`, follows the
#      301 to HTTPS and cannot complete it. Site serves 200s. Not fixed.
#   4. `ssl_stapling ignored, no OCSP responder URL` warnings on nginx reload
#      are benign and pre-existing — Let's Encrypt dropped the OCSP URL from
#      its certs. Present for zdenovo.com and fakturant.zdenovo.com too.
#
# MANUAL STEPS (not replayable — done by the user in the Cloudflare dashboard)
#   - Created A record: terraform-quiz -> 46.225.105.62, GREY cloud (DNS only).
#     Grey cloud is required for ACME HTTP-01: the zone has Always Use HTTPS
#     ON, which 301s the challenge before it reaches the origin.
#   - STILL PENDING at time of writing: flip that record to Proxied (orange).
#
# SAFETY: previews by default. Re-run the deploy only with EXECUTE=1.
#   ./deploy-20260903-1920-993194e.sh            # preview
#   EXECUTE=1 ./deploy-20260903-1920-993194e.sh  # actually run
# ⚠️  = mutates production / touches the live server.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

REPO=/home/zdenek/projects/zdenovo/backend
EXECUTE="${EXECUTE:-0}"

run() {
  if [ "$EXECUTE" = "1" ]; then echo "+ $*"; "$@"
  else echo "[preview] $*"; fi
}

echo "=== [1/9] Local verification (read-only) ==="
run bash -c "cd $REPO/backend && uv run pytest -q --ignore=tests/test_frontend.py --ignore=tests/test_e2e.py"
# Result: 502 passed (534 with the unrelated link-validator WIP present).
run bash -c "cd $REPO && ./scripts/dev-deploy.sh --no-test"
run curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/projects/terraform-quiz
run curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/static/quiz/index.html

echo "=== [2/9] Confirm the Cloudflare A record, bypassing local DNS cache ==="
# Must return the ORIGIN ip (grey cloud), not 104.21.x / 172.67.x.
run curl -s -H 'accept: application/dns-json' \
  'https://cloudflare-dns.com/dns-query?name=terraform-quiz.zdenovo.com&type=A'

echo "=== [3/9] ACME challenge path must be 404, never 301 ==="
# A 301 here means Always-Use-HTTPS is intercepting and certbot will fail.
run curl -sI --resolve terraform-quiz.zdenovo.com:80:46.225.105.62 \
  http://terraform-quiz.zdenovo.com/.well-known/acme-challenge/probe

echo "=== [4/9] Push ==="
run git -C "$REPO" push origin main   # pre-push hook: tests + bandit + pip-audit + route auth

echo "=== [5/9] ⚠️  Pull on the server — deliberately NOT 'make prod' yet ==="
# make prod regenerates app.conf and restarts nginx; if the new server block
# references a cert that does not exist, nginx will not start and the whole
# site goes down. Cert first, always.
run ssh zdenovo "cd /opt/zdenovo && git pull --ff-only"

echo "=== [6/9] ⚠️  Issue the certificate (cert first, then deploy) ==="
# Safe by construction: if certbot fails, make stops before touching app.conf
# and nginx keeps serving the working config. Backgrounded — it can outlive a
# foreground tool timeout, which is what caused incident 1 above.
run ssh zdenovo "cd /opt/zdenovo && timeout 300 make cert-init-terraform-quiz"

echo "=== [7/9] Verify the cert + subdomain against the ORIGIN (grey cloud) ==="
run bash -c "echo | openssl s_client -connect 46.225.105.62:443 \
  -servername terraform-quiz.zdenovo.com 2>/dev/null | openssl x509 -noout -subject -dates"
run curl -s -o /dev/null -w '%{http_code}\n' \
  --resolve terraform-quiz.zdenovo.com:443:46.225.105.62 https://terraform-quiz.zdenovo.com/

echo "=== [8/9] ⚠️  Full production deploy ==="
run ssh zdenovo "cd /opt/zdenovo && make prod"

echo "=== [9/9] Verify production ==="
for u in / /projects /projects/terraform-quiz /projects/fakturant /sitemap.xml; do
  run curl -s -o /dev/null -w "%{http_code} $u\n" -A 'Mozilla/5.0' "https://zdenovo.com$u"
done
run curl -s -o /dev/null -w '%{http_code} fakturant\n' -A 'Mozilla/5.0' https://fakturant.zdenovo.com/
run ssh zdenovo "cd /opt/zdenovo && make check"

echo
echo "ROLLBACK (if the site breaks):"
echo "  ssh zdenovo \"docker exec zdenovo-nginx-1 nginx -t\""
echo "  ssh zdenovo \"cd /opt/zdenovo && docker compose -f docker-compose.prod.yml logs nginx --tail 30\""
echo "  ssh zdenovo \"cd /opt/zdenovo && git revert HEAD --no-edit && make prod\""
