---
name: deploy
description: Deploy the current main branch to the Hetzner production server (zdenovo.com). Runs tests, commits, pushes, and SSHes in to pull + rebuild.
argument-hint: [optional commit message]
---

# Deploy to Production

Deploy the current state to https://zdenovo.com on the Hetzner VPS.

## Prerequisites

- SSH alias `zdenovo` must be configured in `~/.ssh/config`
- `.env` must have `DOMAIN` set
- App must be running locally on `localhost:8080` for pre-push tests

## Steps

1. **Check for uncommitted changes.** Run `git status` in the repo root (`/home/zdenek/projects/zdenovo/backend`).

2. **If there are changes to commit:**
   - Stage the relevant files (never stage `.env` or `secrets/`)
   - Commit with a message. If `$ARGUMENTS` is provided, use it as the commit message. Otherwise, draft one from the diff.
   - The commit message must end with `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

3. **Push to main.** Run `git push origin main`. The pre-push hook will automatically run 126+ unit tests and 37 Playwright frontend tests. If tests fail, fix the issue and retry — do NOT use `--no-verify`.

4. **Deploy to server.** SSH in and pull + rebuild:
   ```bash
   ssh zdenovo "cd /opt/zdenovo && git pull --ff-only && docker compose -f docker-compose.prod.yml up --build -d web nginx"
   ```

5. **Verify.** Check the site is up:
   ```bash
   python3 -c "
   import urllib.request, json
   req = urllib.request.Request('https://zdenovo.com/api/posts', headers={'User-Agent': 'Mozilla/5.0'})
   r = urllib.request.urlopen(req, timeout=10)
   posts = json.loads(r.read())
   print(f'Site live: {len(posts)} posts, status {r.status}')
   "
   ```

6. **Report the result.** Show:
   - Commit hash that was deployed
   - Whether the build succeeded
   - Verification result (status code, post count)
   - Link: https://zdenovo.com

## If something goes wrong

- **Pre-push tests fail:** Fix the failing test, commit the fix, push again.
- **Server build fails:** Check logs with `ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml logs web --tail 30"`
- **Site down after deploy:** Roll back with `ssh zdenovo "cd /opt/zdenovo && git revert HEAD --no-edit && docker compose -f docker-compose.prod.yml up --build -d web nginx"`

## Do NOT

- Skip the pre-push hook with `--no-verify`
- Deploy from a branch other than `main`
- Modify secrets during a code deploy — use `make secret-set` separately
- Push to the server without committing first (the server does `git pull`)
