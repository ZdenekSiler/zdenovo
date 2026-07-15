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

## Steps

1. **Parse the argument.** `$ARGUMENTS` gives a topic, optionally a spec type and part count.
   Default type is `deep-dive`; default part count comes from the type in
   `series_types.json` (usually 4).

2. **List the available spec types** if unsure:
   ```bash
   curl -s http://localhost:8080/api/series | python3 -m json.tool   # existing series
   cat backend/data/series_types.json                                # available types
   ```

3. **Kick off the series.** This returns immediately (202) with the planned outline;
   the drafts generate in the background.
   ```bash
   curl -s -X POST http://localhost:8080/api/series/generate \
     -H "Content-Type: application/json" \
     -d '{"topic": "<topic>", "series_type": "deep-dive", "parts": 4, "guidance": ""}'
   ```
   `parts` and `guidance` are optional. `parts` must be 2–8.

4. **Report the plan.** Show the returned `series_title`, `series_description`, and each
   part's `part_number` / `title` / `angle`. Tell the user drafts are generating and link
   to `http://localhost:8080/admin/drafts`.

5. **Watch drafts appear.** Each part shows up in `/admin/drafts` as it finishes
   (`topic_id = series:<series_id>`). Generation of N parts takes several minutes total.
   ```bash
   curl -s http://localhost:8080/api/drafts | python3 -m json.tool
   ```

6. **Review and publish each part** with the normal draft flow — edit at the preview,
   regenerate-with-remarks, or approve:
   ```bash
   curl -X POST http://localhost:8080/api/drafts/<id>/approve
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
