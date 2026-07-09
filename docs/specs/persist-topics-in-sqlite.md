# Spec: persist-topics-in-sqlite

## Overview
Move the topic pool from the git-tracked, image-baked `backend/data/daily_topics.json` into a SQLite `topics` table in the persistent `db_data` volume (`DB_DIR=/data`, same volume as `blog.db`). This makes runtime-discovered topics survive `make prod` container rebuilds, and preserves the "already covered" memory so trending-topic discovery never re-suggests a subject that already exists as a topic, a generated draft, or a published post.

## Current State
- `topics_api.py` stores topics in `daily_topics.json`: `_load_topics()` reads it, `_save_topics()` overwrites it, `create_topics()` does load→append→save. `_slugify`, `_enrich_topics`, `category_balance` derive status/draft_id from the `drafts` table (not stored).
- Consumers: `main.py` (admin HTML routes import `_load_topics`, `_save_topics`, `_slugify`, `create_topics`), `drafts_api.py` (imports `TopicIn`, `create_topics`, `_load_topics`; `_load_daily_topics()` wraps rows in `PostBrief`).
- `drafts_api.discover_and_replenish_topics()` dedups candidates only against current file topics (`existing_dicts`) via `_is_duplicate_candidate`, plus prompt context `<existing_posts>` (published) + `<existing_topics>` (file topics). Pending drafts' subjects are in neither the dedup set nor the prompt.
- On `make prod` the image rebuilds and `daily_topics.json` resets to the 26 committed rows; runtime topics + coverage memory are wiped. `blog.db` persists (volume), so published posts survive but pending-draft topics do not.
- Import direction (`.claude/rules/architecture.md`): one-way `posts_api → generate_api → drafts_api → topics_api`; `topics_api` never imports `drafts_api` at module level (its `/discover` route lazy-imports it). `db` is the foundation and imports nothing internal.

## Files to Modify
- **`backend/db.py`** — Add `topics` table to `init_db()` (CREATE IF NOT EXISTS + PRAGMA-based column migration pattern already used for posts/drafts). Add a one-time seed: when `topics` is empty, import rows from `daily_topics.json` (the file becomes a seed, analogous to `seed_posts.json`). Idempotent — never re-seeds a non-empty table, so redeploys preserve runtime topics.
- **`backend/routers/topics_api.py`** — Re-back `_load_topics()`, `_save_topics()`, `create_topics()` with the DB while keeping identical signatures/return shapes (so `main.py` and `drafts_api` imports are untouched). `_load_topics()` returns brief-shaped dicts (`id, title_hint, description, audience, tone, tags, outline`) ordered by insertion; JSON-decode `tags`/`outline`. `_save_topics(list)` = full-table replace inside one transaction (preserves the load→mutate→save call sites in `update_topic`/`delete_topic` and `main.py`). Keep `_slugify`, `_enrich_topics`, `category_balance` unchanged.
- **`backend/routers/drafts_api.py`** — Add `_existing_subjects()` returning `[{title_hint, tags}]` from **topics + drafts (title→title_hint, tags) + published posts (title→title_hint, tags)**. In `discover_and_replenish_topics()`, dedup candidates against this combined corpus instead of file topics only. Optionally also feed pending-draft titles into the discovery prompt context (extend the `existing_topics` argument path) — at minimum the local `_is_duplicate_candidate` filter must use the full corpus.
- **`backend/tests/test_topics.py`** — Replace the file-based `topics_file` fixture and all `json.loads(topics_file.read_text())` assertions with DB-backed seeding + assertions via `GET /api/topics` or a direct `topics` query.
- **`docs/architecture.md`** — Add `topics` to the persisted-tables/key-decisions section per architecture checklist step 7.

## Files to Create
- None required. `daily_topics.json` is retained as the seed source (like `seed_posts.json`); no new module or router is needed, so the import-direction rules are unaffected.

## Implementation Plan
1. `db.py`: define `topics` schema (`id TEXT PK, title_hint, description, audience, tone, tags TEXT, outline TEXT, created_at TEXT`), add the CREATE + migration block, and the empty-table seed loop reading `daily_topics.json` (`json.dumps` the `tags`/`outline` lists). Add a `topic_row_to_dict` helper that JSON-decodes list columns and omits non-brief columns so `PostBrief(**item)` in `_load_daily_topics()` still validates.
2. `topics_api.py`: rewrite `_load_topics`/`_save_topics`/`create_topics` over `get_conn()`. Preserve `create_topics` id-dedup logic (slugify, suffix on collision). Verify `list_topics`, `get_topic`, `update_topic`, `delete_topic`, `create_topic`, and `main.py` admin routes work unchanged against the new helpers.
3. `drafts_api.py`: add `_existing_subjects()`; wire it into `discover_and_replenish_topics()` as the dedup corpus. Confirm `generate_daily_drafts`/`generate_single_topic` still resolve topics through `_load_topics()`.
4. First prod deploy: existing volume has a `blog.db` with no `topics` table → `init_db()` creates it and seeds the 26 committed rows once. Subsequent deploys skip seeding.
5. Update tests (below); run the suite.

## Tests Needed
- **db seed:** fresh DB seeds N topics from `daily_topics.json`; re-running `init_db()` on a non-empty table does NOT duplicate or reset (redeploy-persistence proof).
- **topics CRUD over DB:** port existing `test_topics.py` cases (create/update/delete/list/get, id dedup, `create_topics` batch) to assert against DB/API instead of the JSON file.
- **discovery dedup:** candidate whose subject matches (a) an existing topic, (b) an existing draft's title/tags, (c) a published post's title/tags is filtered out; a genuinely fresh candidate is accepted. Mirror the existing `test_discover_topics_route_returns_summary` mocking style.
- **enrich/status:** `_enrich_topics` still maps draft_pending/published/available correctly against DB-backed topics.

## Risks & Trade-offs
- **`_save_topics` full-table replace** is simple and keeps every caller unchanged, but is O(all rows) and briefly empties the table mid-transaction; acceptable at this data volume (tens of rows) and it's atomic within one connection. Alternative (targeted upsert/delete helpers) would require editing `main.py` and route bodies.
- **PostBrief strictness:** `_load_daily_topics()` does `PostBrief(**item)`; `_load_topics()` must return only brief fields (exclude `created_at`) or `PostBrief` may reject extra keys — enforce via the row-to-dict helper.
- **Seed timing:** seeding keys off "table empty," so if an admin ever deletes all topics the next `init_db()` re-seeds — a deliberate, low-risk behavior worth noting.
- **Import direction preserved:** the dedup query spans `topics`+`drafts`+`posts`, but lives in `drafts_api` (which already reads all three via `get_conn`), so no new cross-router imports and the lazy `topics_api → drafts_api` exception stays intact.
- **daily_topics.json role change:** it stops being the live store and becomes a seed; document this so future edits to the file are understood to only affect fresh databases.

## Critical Files for Implementation
- `backend/db.py`
- `backend/routers/topics_api.py`
- `backend/routers/drafts_api.py`
- `backend/tests/test_topics.py`
- `backend/data/daily_topics.json`
