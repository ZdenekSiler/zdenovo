---
name: deploy
description: Deploy the blog to dev (local Docker) or prod (Hetzner VPS). Usage: /deploy dev or /deploy prod [commit message].
argument-hint: dev | prod [optional commit message]
---

# Deploy Skill

Deploys the zdenovo blog. The first word of `$ARGUMENTS` is the target (`dev` or `prod`). Everything after it is an optional commit message.

Parse `$ARGUMENTS`:
- If it starts with `dev`  → follow the **Deploy Dev** section below.
- If it starts with `prod` → follow the **Deploy Prod** section below.
- If missing or neither   → tell the user: "Usage: /deploy dev  or  /deploy prod [commit message]" and stop.

---

## Deploy Dev

Start (or restart) the local development environment.

### What "dev" means
- Single Docker container built from the repo's `Dockerfile`
- Container port 8000 → host port 8080 (no nginx, no SSL)
- SQLite DB lives in `./data/` (bind-mounted, persists between restarts)
- `.env` is bind-mounted read-only; DB schema migrates automatically on startup

### Steps

1. **Run the dev-deploy script:**
   ```bash
   cd /home/zdenek/projects/zdenovo/backend
   ./scripts/dev-deploy.sh
   ```
   This handles everything: prerequisite checks, tests, stopping old containers,
   building, starting, and health-checking. It will print results as it goes.

2. **If the script fails**, diagnose and fix:
   - `Docker is not running` → ask user to start Docker Desktop
   - `Tests failed` → show the failing test output, offer to fix or re-run with `--no-test`
   - `App did not respond` → run `docker compose logs web` and show the tail

3. **Report the result:**
   - Whether it succeeded or failed
   - URL: http://localhost:8080
   - Admin: http://localhost:8080/admin
   - Tip: `docker compose logs -f web` to tail logs, `docker compose down` to stop

---

## Deploy Prod

Deploy the current branch to https://zdenovo.com on the Hetzner VPS.

### What "prod" means
- SSH into `zdenovo` (alias in `~/.ssh/config` → Hetzner VPS)
- Server runs `git pull --ff-only && make prod` which:
  - Runs a pre-deploy security check
  - Backs up `blog.db` automatically
  - Builds the production Docker image
  - Restarts nginx + web container

### Prerequisites
- SSH alias `zdenovo` must be configured in `~/.ssh/config`
- `.env` must have `DOMAIN` set
- Must be on `main` branch (prod deploys main only)
- **Dev must have been tested this session.** If `/deploy dev` was not run and the key
  pages verified (home, a blog post, reactions, admin) in this conversation, ask the user
  to confirm before proceeding: "Have you tested this on dev (localhost:8080) first?"
  Do NOT deploy to prod if the answer is no or unclear.

### Steps

1. **Check current branch.**
   ```bash
   git -C /home/zdenek/projects/zdenovo/backend branch --show-current
   ```
   If NOT on `main`: tell the user the current branch and ask them to merge to main first. Stop here — do not deploy from a feature branch.

2. **Check for uncommitted changes.**
   ```bash
   git -C /home/zdenek/projects/zdenovo/backend status --short
   ```
   If there are changes:
   - Stage relevant files (never stage `.env`, `secrets/`, `*.db`, `*.bak`)
   - Commit with the message from `$ARGUMENTS` (everything after "prod"), or draft one from `git diff --cached`

3. **Push to origin main.**
   ```bash
   git -C /home/zdenek/projects/zdenovo/backend push origin main
   ```
   The pre-push hook runs tests automatically. If it fails, fix the issue and retry. Do NOT use `--no-verify`.

4. **Deploy to server.**
   ```bash
   ssh zdenovo "cd /opt/zdenovo && git pull --ff-only && make prod"
   ```
   This may take 1–2 minutes (Docker build). Stream the output so the user can see progress.

5. **Verify the site is live.**
   ```bash
   python3 -c "
   import urllib.request, json
   req = urllib.request.Request('https://zdenovo.com/api/posts', headers={'User-Agent': 'Mozilla/5.0'})
   r = urllib.request.urlopen(req, timeout=15)
   posts = json.loads(r.read())
   print(f'Live: {len(posts)} posts, HTTP {r.status}')
   "
   ```

6. **Report the result:**
   - Commit hash deployed (`git -C /home/zdenek/projects/zdenovo/backend rev-parse --short HEAD`)
   - Build success/failure
   - Verification: post count + status code
   - Link: https://zdenovo.com

### If something goes wrong

- **Pre-push tests fail:** Fix the failing test, commit the fix, push again.
- **Server build fails:**
  ```bash
  ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml logs web --tail 30"
  ```
- **Site down after deploy (rollback):**
  ```bash
  ssh zdenovo "cd /opt/zdenovo && git revert HEAD --no-edit && make prod"
  ```

### Do NOT
- Use `--no-verify` to skip the pre-push hook
- Deploy from a branch other than `main`
- Stage `.env`, `secrets/`, `*.db`, or `*.bak` files
- Push to the server without committing first (the server does `git pull`)
