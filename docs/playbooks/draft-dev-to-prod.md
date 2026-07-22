# Playbook: Move a Draft from Dev to Prod (and fix its hero image)

A hands-on, copy-pasteable walkthrough of how a generated draft gets from your laptop's
dev DB into the **production** database — the exact byte-for-byte reviewed content, without
regenerating — plus how to swap a post's hero image. Every command is annotated with **why**
it's run and **what** its output tells you. Prod-mutating steps are flagged ⚠️.

> **TL;DR** — a draft is a *row in the `drafts` table*, not a file in git, so `make prod`
> (which is `git pull && rebuild`) never carries it across. The prod DB lives inside a Docker
> **named volume** you can't touch from the host — so you move data with `docker compose cp`
> (copy files in/out) and run code against it with `docker compose exec` (run a process inside
> the container). The runnable version of this whole playbook is
> [`scripts/draft-to-prod.sh`](../../scripts/draft-to-prod.sh).

## Why not just `make prod`?

| What | Where it lives | Moves on `make prod`? |
|------|----------------|-----------------------|
| Code, templates, CSS | git | ✅ yes (`git pull` + rebuild) |
| Posts / **drafts** / comments | SQLite `drafts`/`posts` table | ❌ no — it's runtime data in the `db_data` volume |

So publishing new *code* is `make prod`; moving a *draft* is this playbook.

## Prerequisites

- Dev running on `localhost:8080` (`./scripts/dev-deploy.sh`)
- SSH alias `zdenovo` in `~/.ssh/config` (→ the Hetzner VPS)
- `ADMIN_PASSWORD` and `UNSPLASH_ACCESS_KEY` in `backend/.env`
- The draft already generated on dev (see step 0)

---

## Step 0 — Generate the draft on dev (authenticated API)

`POST /api/posts/generate` is **admin-guarded** (`Depends(require_admin)`), and auth is a
**session cookie**, not a header/token. So you log in first to get the cookie, then reuse it.

```bash
# Read the admin password from .env into a var WITHOUT printing it (never echo secrets).
ADMIN_PW=$(grep -E '^ADMIN_PASSWORD=' .env | head -1 | cut -d= -f2-)

# Log in; -c writes the session cookie to a jar. --data-urlencode is safe for odd chars.
curl -s -o /dev/null -c /tmp/jar.txt -X POST http://localhost:8080/admin/login \
  --data-urlencode "password=$ADMIN_PW" --data-urlencode "next=/admin/posts"

# Confirm the session works: -w '%{http_code}' prints ONLY the status → expect 200.
curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/jar.txt http://localhost:8080/admin/posts

# Generate. -b sends the cookie jar. Takes ~1-2 min (Claude write + review + up to 3 retries).
curl -s -b /tmp/jar.txt -X POST http://localhost:8080/api/posts/generate \
  -H "Content-Type: application/json" \
  -d '{"description":"<your topic>","tags":["ai","llm"]}' | python3 -m json.tool
```

The response is a `DraftOut` — note its **`id`** and `quality_score`. It's saved with
`status="pending"` and shows up at `/admin/drafts`.

> **Gotcha we hit:** calling the endpoint without the cookie returns **HTTP 303** in ~2 ms —
> that's the redirect to `/admin/login`, i.e. "you're not authenticated," not a generation.

Flags glossary: `-s` silent, `-o /dev/null` discard body, `-w` format string,
`-c` write cookies, `-b` send cookies, `-X` method, `-d` body.

---

## Step 1 — Export the draft row (dev, read-only)

The `drafts` table is self-contained — `sources`, `tags`, and quality fields are JSON
**columns on the row**, no child tables, no foreign keys. So one row is the whole draft.

```bash
python3 scripts/lib/export_draft.py ./data/blog.db <draft_id> /tmp/row.json
```

On dev the DB is a plain bind-mounted file (`./data/blog.db`), so this is a direct read.

---

## Step 2 — Ship the row into the prod container

The prod DB is inside the Docker **named volume** `db_data:/data`. You can't `scp` straight
to it — the volume only exists *inside* the container. Two hops:

```bash
# Hop 1: laptop → prod HOST (/tmp on the VPS)
scp /tmp/row.json zdenovo:/tmp/row.json
scp scripts/lib/insert_draft.py zdenovo:/tmp/insert_draft.py

# Hop 2: prod host → INSIDE the container (host /tmp → container /tmp)
ssh zdenovo "cd /opt/zdenovo && \
  docker compose -f docker-compose.prod.yml cp /tmp/row.json      web:/tmp/row.json && \
  docker compose -f docker-compose.prod.yml cp /tmp/insert_draft.py web:/tmp/insert_draft.py"
```

### 🐳 Docker command deep-dive

- **`docker compose -f docker-compose.prod.yml`** — `-f` selects the prod compose file (the
  default would be `docker-compose.yml`). Everything below targets the prod stack.
- **`... cp <src> web:<dst>`** — copy a file between host and the **`web`** service's
  container. Direction is by which side has the `service:` prefix: `cp host web:/path` copies
  **in**, `cp web:/path host` copies **out**. This is how you both deliver scripts and pull
  the DB out for a backup.
- **`... exec -T web <cmd>`** (next step) — run `<cmd>` inside the already-running `web`
  container. **`-T` disables the pseudo-TTY** — essential when the command is driven over ssh
  / piped (no interactive terminal), otherwise Docker errors with *"the input device is not a
  TTY."*
- **Why a temp file inside the container?** `exec` runs code, but that code needs the JSON to
  read. `cp` puts the JSON where the `exec`'d process can open it (`/tmp` inside the container).

---

## Step 3 — ⚠️ Insert into the prod DB (backup first)

```bash
ssh zdenovo "cd /opt/zdenovo && \
  docker compose -f docker-compose.prod.yml exec -T web python3 /tmp/insert_draft.py /tmp/row.json"
```

`insert_draft.py` runs **inside** the container (so `DB_DIR=/data` points at the real prod DB)
and is safe by construction:

1. **Backs up** `blog.db` → `blog.db.pre-insert-<timestamp>.bak` via SQLite's online-backup
   API (safe even while the app holds the DB open).
2. **Intersects columns** between the JSON and the live table — tolerating schema drift. (Real
   example: dev has a `related_posts` column that prod doesn't; it's simply dropped on copy.)
3. **`INSERT OR REPLACE`** keyed on `id` → idempotent, safe to re-run.
4. **Verifies** the row is present and prints the new total draft count.

Expected tail: `inserted: id=… status=pending score=…` then `OK`. The draft now appears at
`https://zdenovo.com/admin/drafts` for review/approval.

---

## Step 4 — Swap the hero image (optional)

Images come from the Unsplash **search API** by query (see `_fetch_unsplash_image()` in
`generate_api.py`). If the auto-picked image is wrong (e.g. an OpenAI photo on a Qwen post),
resolve a better one and update the `image` column on **both** dev and prod.

```bash
# 1. Resolve a URL (dev-side). Key comes from the ENV, never argv (won't leak into `ps`).
UNSPLASH_ACCESS_KEY=$(grep -E '^UNSPLASH_ACCESS_KEY=' .env | head -1 | cut -d= -f2-)
url=$(UNSPLASH_ACCESS_KEY="$UNSPLASH_ACCESS_KEY" \
      python3 scripts/lib/fetch_unsplash.py "server room data center" 2JJ3wBHu4_0)
printf '%s\n' "$url" > /tmp/image.txt   # pass via file so the '&'-heavy URL needs no escaping

# 2. ⚠️ DEV write (DB_DIR points the shared script at ./data)
DB_DIR=./data python3 scripts/lib/update_draft_image.py <draft_id> /tmp/image.txt

# 3. ⚠️ PROD write (same script, run inside the container)
scp scripts/lib/update_draft_image.py zdenovo:/tmp/ && scp /tmp/image.txt zdenovo:/tmp/
ssh zdenovo "cd /opt/zdenovo && \
  docker compose -f docker-compose.prod.yml cp /tmp/update_draft_image.py web:/tmp/update_draft_image.py && \
  docker compose -f docker-compose.prod.yml cp /tmp/image.txt web:/tmp/image.txt && \
  docker compose -f docker-compose.prod.yml exec -T web python3 /tmp/update_draft_image.py <draft_id> /tmp/image.txt"
```

Passing a **`photo_id`** (the last arg) pins an exact image so dev and prod match; omit it to
take the current top search hit. `update_draft_image.py` backs up (`…pre-img-<ts>.bak`) before
writing and prints old → new for confirmation.

> **Tip:** before committing to an image, list a few candidates and skim their
> `alt_description` to avoid brand logos:
> ```bash
> UNSPLASH_ACCESS_KEY=$(grep -E '^UNSPLASH_ACCESS_KEY=' .env | cut -d= -f2-) \
>   python3 - <<'PY'
> import os,json,urllib.parse,urllib.request
> qs=urllib.parse.urlencode({"query":"server room data center","per_page":6,"orientation":"landscape"})
> req=urllib.request.Request("https://api.unsplash.com/search/photos?"+qs,
>   headers={"Authorization":"Client-ID "+os.environ["UNSPLASH_ACCESS_KEY"]})
> for p in json.load(urllib.request.urlopen(req))["results"]:
>   print(p["id"], "|", p.get("alt_description"))
> PY
> ```

---

## The runnable version

Everything above is wrapped in [`scripts/draft-to-prod.sh`](../../scripts/draft-to-prod.sh),
which echoes each command, flags DEV/PROD writes, and redacts secrets:

```bash
./scripts/draft-to-prod.sh generate "Qwen3.8 Max vs closed frontier models" ai,llm
./scripts/draft-to-prod.sh copy <draft_id>
./scripts/draft-to-prod.sh set-image <draft_id> "server room data center" 2JJ3wBHu4_0

# See the exact command sequence without touching prod:
DRY_RUN=1 ./scripts/draft-to-prod.sh copy <draft_id>
# Full shell trace:
DEBUG=1   ./scripts/draft-to-prod.sh copy <draft_id>
```

---

## Rollback

Every write leaves a timestamped backup *inside the container*. To restore:

```bash
# List backups
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml exec -T web ls -la /data | grep '\.bak'"

# Restore one over the live DB (⚠️ overwrites current data)
ssh zdenovo "cd /opt/zdenovo && docker compose -f docker-compose.prod.yml exec -T web \
  cp /data/blog.db.pre-insert-<timestamp>.bak /data/blog.db"
```

Or delete the mistaken draft instead via the API:
`curl -X DELETE https://zdenovo.com/api/drafts/<id>` (needs an admin session).

## Secret-handling rules (applied throughout)

- Read secrets from `.env` into a shell variable; **never** `echo`/`cat` them.
- Prefer passing secrets via **environment** over argv (argv shows up in `ps`).
- In any command log or recap, show the secret as `<redacted>` (e.g. `password=<redacted>`).
- See [`.claude/rules/git.md`](../../.claude/rules/git.md) and
  [`.claude/rules/debugging.md`](../../.claude/rules/debugging.md).
