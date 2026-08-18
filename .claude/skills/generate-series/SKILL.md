---
name: generate-series
description: Generate a multi-part blog series from one topic + a spec type (deep-dive / overview / tutorial). Plans N related parts, then generates each as a draft assigned to a new series. Drafts land in admin review.
argument-hint: <topic> [type: deep-dive|overview|tutorial] [parts: N]
---

# Generate Blog Series

Generate a coherent multi-part series (e.g. a 4-part LangChain deep dive) in one action.

## How it works

The series pipeline builds on the single-post generator:
1. A planner call (Claude Haiku, `backend/data/prompts/series_plan_system.md`) expands the
   topic + spec type into an ordered outline of N parts via the `plan_series` tool.
2. A new `series` row is created up front.
3. Each part is generated in the **background** using the normal post pipeline
   (Sonnet generate + Haiku slop review + retries + web-search sources), assigned the
   `series_id` and its `series_order`.
4. Parts land in `drafts` (status `pending`) as they finish — approve each one normally;
   the series assignment carries into the published post so the "Part N of M" nav works.

The spec types live in `backend/data/series_types.json` (`deep-dive`, `overview`,
`tutorial`) — each defines the arc and per-part guidance fed to the planner.

## Auth: the generate route needs an admin session

Every mutating `/api/series` route (`POST /api/series`, `POST /api/series/generate`,
`GET /api/series/{id}/progress`, `DELETE`) is behind `require_admin`. Without a session
cookie they return **303** to `/admin/login` — not a JSON error, so a plain `curl | json.tool`
just fails to parse. Reads (`GET /api/series`, `GET /api/drafts`) are public.

Log in once and reuse the cookie jar. Read the password without echoing it
(see @.claude/rules/git.md — never print `.env`):

```bash
cd /home/zdenek/projects/zdenovo/backend
ADMIN_PW=$(python3 -c "
import pathlib
for line in pathlib.Path('.env').read_text().splitlines():
    if line.startswith('ADMIN_PASSWORD='):
        print(line.split('=', 1)[1].strip().strip('\"').strip(\"'\")); break")
curl -s -o /dev/null -w 'login %{http_code}\n' -c /tmp/zdenovo-admin.cookies \
  -X POST http://localhost:8080/admin/login \
  --data-urlencode "password=$ADMIN_PW" --data-urlencode "next=/admin/posts"
unset ADMIN_PW   # 303 = success
```

Then pass `-b /tmp/zdenovo-admin.cookies` on every admin call below.

## Request field limits (`SeriesGenerateIn`)

Exceeding any of these returns **422** with a `string_too_long` / range detail — check them
before sending, especially `guidance`, which is easy to blow past:

| Field | Limit |
|-------|-------|
| `topic` | 1–300 chars, required |
| `series_type` | required — a `series_types.json` id (`deep-dive` / `overview` / `tutorial`) |
| `parts` | optional, 2–8 |
| `guidance` | optional, **max 1000 chars** |

If your guidance is longer than 1000 chars, compress it rather than truncating mid-sentence:
keep the fixed part breakdown and the must-cover axes, drop prose. Long-form direction that
won't fit belongs in `series_types.json` as a new spec type instead.

## Steps

1. **Parse the argument.** `$ARGUMENTS` gives a topic, optionally a spec type and part count.
   Default type is `deep-dive`; default part count comes from the type in
   `series_types.json` (usually 4).

2. **List the available spec types** if unsure:
   ```bash
   curl -s http://localhost:8080/api/series | python3 -m json.tool   # existing series
   cat backend/data/series_types.json                                # available types
   ```

3. **Kick off the series.** Needs the admin cookie (see Auth above). Returns immediately
   (202) with the planned outline; the drafts generate in the background.
   ```bash
   curl -s -w '\nHTTP %{http_code}\n' -b /tmp/zdenovo-admin.cookies \
     -X POST http://localhost:8080/api/series/generate \
     -H "Content-Type: application/json" \
     -d '{"topic": "<topic>", "series_type": "deep-dive", "parts": 4, "guidance": ""}'
   ```
   Expect **202**. A **303** means the cookie is missing or stale — log in again. A **422**
   means a field limit was hit (see the table above). Write long `guidance` to a file and
   send it with `-d @file.json` so shell quoting doesn't mangle it.

4. **Report the plan.** Show the returned `series_title`, `series_description`, and each
   part's `part_number` / `title` / `angle`. Tell the user drafts are generating and link
   to `http://localhost:8080/admin/drafts`.

5. **Watch drafts appear.** Each part shows up in `/admin/drafts` as it finishes.
   Generation of N parts takes several minutes total. Poll the progress endpoint —
   it reports pending drafts and published posts for the series in one shot (admin):
   ```bash
   curl -s -b /tmp/zdenovo-admin.cookies \
     http://localhost:8080/api/series/<series_id>/progress | python3 -m json.tool
   ```
   Or filter the public drafts list on `series_id`:
   ```bash
   curl -s http://localhost:8080/api/drafts | python3 -c "
   import sys, json
   for x in json.load(sys.stdin):
       if x.get('series_id') == '<series_id>':
           print(x['series_order'], x['id'], x['status'], x['title'])"
   ```

6. **Verify each part's sources before approving.** Every part runs its own web-search
   sources call, so a series multiplies the chance of a dead reference. Check them all at once:
   ```bash
   curl -s http://localhost:8080/api/drafts | python3 -c "
   import sys, json, urllib.request
   UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
   for d in json.load(sys.stdin):
       if d.get('series_id') != '<series_id>': continue
       for s in d.get('sources') or []:
           try:
               req = urllib.request.Request(s['url'], headers={'User-Agent': UA})
               print(urllib.request.urlopen(req, timeout=12).status, d['series_order'], s['url'])
           except Exception as e:
               print('FAIL', getattr(e, 'code', type(e).__name__), d['series_order'], s['url'])"
   ```
   403/429 means the host blocks bots (Medium, DataCamp), **not** that the link is dead — only
   404/410 and DNS/connection failures prove that. Drop dead ones via PATCH; don't bulk-delete
   every non-200.

7. **Review and publish each part** with the normal draft flow — edit at the preview,
   regenerate-with-remarks, or approve (approve is admin-only, so pass the cookie):
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/zdenovo-admin.cookies \
     -X POST http://localhost:8080/api/drafts/<id>/approve
   ```

## Cost note

A series costs roughly N× a single post (each part runs up to 3 Sonnet attempts + a Haiku
review + a web-search sources call), plus one cheap Haiku planning call. Keep `parts` modest
and test with `parts: 2` first. See the cost-management section in `docs/architecture.md`.

## Rules for editing prompts / spec types

| File | Purpose |
|------|---------|
| `backend/data/series_types.json` | The spec templates — arc + per-part guidance, default part counts. Add or tune types here. |
| `backend/data/prompts/series_plan_system.md` | Planner system prompt — how the outline is shaped. |
| `backend/data/prompts/series_plan_tool.json` | `plan_series` tool schema (series_title, series_description, parts[]). |

The per-post voice/formatting still come from `blog_system.md` / `blog_tool.json` (shared
with `/generate-post`).

## Do NOT

- Modify `generate_api.py` or `series_api.py` for prompt/spec content — edit the JSON/MD
  templates instead.
- Expect the request to block until all posts exist — it returns after planning; parts
  generate in the background.
- Approve drafts without reviewing them first.
- Echo, log, or paste the admin password — read it into a variable and `unset` it after
  login, and keep the cookie jar out of the repo.
- Pad `guidance` up to the 1000-char cap with filler to "steer harder" — durable direction
  belongs in `series_types.json`.
