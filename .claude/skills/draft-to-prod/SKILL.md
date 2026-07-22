---
name: draft-to-prod
description: Copy a reviewed draft from the dev DB into PROD's review queue so it can be approved on zdenovo.com. Usage: /draft-to-prod <draft id | slug | title fragment>.
argument-hint: <draft id | slug | title fragment>  (empty → pick from a list)
---

# Draft → Prod Skill

Copies one draft from the **dev** database into **production**'s `drafts` table, so you can
review and approve it on https://zdenovo.com/admin/drafts. A draft is a DB row (not code), so
`make prod` never carries it — this skill does, exactly, byte-for-byte, with a prod DB backup
taken first.

**This does NOT publish.** The draft lands on prod as `status=pending`; a human still approves
it on `/admin/drafts` to make it live.

## The argument (`$ARGUMENTS`)

Identifies which dev draft to copy. Accept any of — most specific wins:
1. a **draft id** (UUID, e.g. `5e93a1ec-50ca-4bf3-ab07-c056c4579ef7`) — exact;
2. a **slug** (e.g. `hugging-face-got-popped-by-a-robot-...`) — exact;
3. a **title fragment** (case-insensitive substring, e.g. `hugging face`) — fuzzy.

If `$ARGUMENTS` is empty or matches nothing/too much, list candidates and ask.

## Prerequisites
- Dev running on `localhost:8080` (the draft lives in the dev DB).
- SSH alias `zdenovo` configured; prod reachable.
- Reusable tooling present: `scripts/draft-to-prod.sh` + `scripts/lib/` (tracked in git).

## Steps

1. **Resolve the identifier to exactly one dev draft id.** List dev drafts (public endpoint,
   no auth needed):
   ```bash
   curl -s http://localhost:8080/api/drafts | python3 -c "
   import sys, json
   for x in json.load(sys.stdin):
       print(x['id'], '|', x['status'], '|', x['slug'], '|', x['title'])"
   ```
   Match `$ARGUMENTS`:
   - looks like a UUID → use it directly (confirm it appears in the list);
   - else exact slug match; else case-insensitive substring of the title.
   - **0 matches** → show the list, tell the user, stop.
   - **>1 match** → show the matches and ask which (AskUserQuestion), or stop and ask.
   Only proceed once you have a single unambiguous id.

2. **Show the resolved draft** (id, title, status, quality score) so the user can see what
   will be copied. If it looks wrong, stop.

3. **⚠️ PROD-MUTATION — copy it to prod** (the script backs up prod `blog.db` first, then
   `INSERT OR REPLACE`s the row — idempotent):
   ```bash
   cd /home/zdenek/projects/zdenovo/backend
   ./scripts/draft-to-prod.sh copy <draft_id>
   ```
   Unsure? Preview with no writes first: `DRY_RUN=1 ./scripts/draft-to-prod.sh copy <draft_id>`.

4. **Verify + report:**
   - the prod review URL: `https://zdenovo.com/admin/drafts/<draft_id>`
   - the backup file the copy printed (`/data/blog.db.pre-insert-<ts>.bak`, inside the web container)
   - the new prod draft count (from the script's `total_drafts_now`)
   - remind the user: **approve on prod** to publish (this skill does not).

## Notes
- **Idempotent:** re-running copies the same row and takes a fresh backup — safe to repeat.
- **Schema drift:** dev's `related_posts` column is dropped on copy (harmless — prod lacks it).
- **Wrong hero image?** Swap it before or after copying with
  `./scripts/draft-to-prod.sh set-image <draft_id> "<query>" [photo_id]`, or use the
  "Change image" picker in the review UI.

## Do NOT
- Approve/publish automatically — leave that to a human on `/admin/drafts`.
- Deploy code (`make prod`) — this skill only moves a draft row.
- Stage, echo, or log `.env` / `secrets/` contents.
