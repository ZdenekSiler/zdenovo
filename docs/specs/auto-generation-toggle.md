# Spec: auto-generation-toggle

## Overview
Add a persisted, global on/off switch (`auto_generation_enabled`) that gates **only** the
scheduled daily draft generation job. When OFF (the default and initial-deploy state), the
02:00 UTC cron job stays registered but no-ops with a log line. Manual generation (the
"Generate today's drafts" button and all `/api/drafts/generate*` endpoints) must keep working
regardless. An admin toggle button on `/admin/drafts` flips the flag via HTMX, mirroring the
existing `toggle_ai_comments` / `_ai_toggle_btn` pattern.

## Current State
- Scheduler is built in `backend/main.py` `lifespan()` (lines 60-70):
  `scheduler.add_job(generate_daily_drafts, "cron", hour=2, minute=0)`.
- `generate_daily_drafts()` lives in `backend/routers/drafts_api.py` (line 260). It backs
  **both** the cron job **and** `POST /api/drafts/generate` (route `trigger_daily_generation`,
  line 306). `drafts_api.py` already has a module logger (`log = logging.getLogger(__name__)`).
- There is **no settings table** in `backend/db.py`. `init_db()` uses the
  `CREATE TABLE IF NOT EXISTS` + `PRAGMA table_info` migration pattern. The DB file is `blog.db`
  under `DB_DIR`, which is the persistent `db_data` volume in prod.
- Existing toggle pattern: `toggle_ai_comments` route (main.py line 505) + `_ai_toggle_btn(slug,
  enabled)` HTML helper (line 517), initial render inlined in `admin_posts.html` (lines 80-89)
  via Jinja `{% if %}/{% else %}`; swaps return the helper string (`hx-target="this"
  hx-swap="outerHTML"`).
- The "Generate today's drafts" button is in `frontend/templates/drafts_list.html` (lines
  74-80). The `/admin/drafts` route is `admin_drafts` (main.py line 605).

## Key design decision (resolves an apparent conflict)
Requirement "guard the body of `generate_daily_drafts`" and "manual trigger must still work"
conflict if the flag check goes literally inside `generate_daily_drafts()`, because the manual
`POST /api/drafts/generate` calls that same function. **Resolution:** keep
`generate_daily_drafts()` pure and add a thin scheduled wrapper that does the gating:

```python
# drafts_api.py
def run_scheduled_generation() -> dict:
    """Scheduler entry point. Gated by the auto_generation_enabled flag so only the
    cron run is guarded — manual triggers call generate_daily_drafts() directly."""
    if db.get_setting("auto_generation_enabled", "0") != "1":
        log.info("Scheduled draft generation skipped — auto_generation_enabled is off")
        return {"generated": 0, "skipped": True}
    return generate_daily_drafts()
```

The scheduler registers `run_scheduled_generation` instead of `generate_daily_drafts`. This
satisfies "keep the cron job registered, guard at fire time" while leaving all manual paths
untouched. (Alternative considered: a `scheduled: bool=False` param on `generate_daily_drafts`;
rejected as it muddies the shared function's signature.)

## Files to Modify
- **`backend/backend/db.py`** — add `settings` KV table to `init_db()`
  (`CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)`; no seed
  row → absent key = OFF). Add helpers `get_setting(key, default=None) -> str | None` and
  `set_setting(key, value) -> None` (upsert via `INSERT ... ON CONFLICT(key) DO UPDATE`).
- **`backend/backend/routers/drafts_api.py`** — `import db`; define
  `AUTO_GEN_SETTING = "auto_generation_enabled"`; add `run_scheduled_generation()` wrapper
  (2-space indent to match this file). Leave `generate_daily_drafts()` unchanged.
- **`backend/backend/main.py`** — (1) import `run_scheduled_generation` and register it in
  `lifespan` instead of `generate_daily_drafts` (line 65). (2) Add
  `POST /admin/drafts/toggle-auto-gen` route mirroring `toggle_ai_comments`: read current, flip,
  `db.set_setting(...)`, return `_auto_gen_toggle_btn(new_val)`. (3) Add
  `_auto_gen_toggle_btn(enabled: bool) -> str` helper next to `_ai_toggle_btn`. (4) In
  `admin_drafts`, pass `auto_gen_enabled = db.get_setting(AUTO_GEN_SETTING, "0") == "1"` into
  the template context.
- **`backend/frontend/templates/drafts_list.html`** — next to the "Generate today's drafts"
  button, add the toggle button with inlined `{% if auto_gen_enabled %}...{% else %}...{% endif %}`
  initial render (label "Auto: on" / "Auto: off", `hx-post="/admin/drafts/toggle-auto-gen"`,
  `hx-target="this"`, `hx-swap="outerHTML"`), matching `admin_posts.html` and the
  `_auto_gen_toggle_btn` output exactly.
- **`backend/docs/architecture.md`** — add a row/note for the new admin route and the `settings`
  table (architecture.md checklist step 7).

## Files to Create
- None. (The KV mechanism reuses `db.py`; no new module/template needed.)

## Implementation Plan
1. `db.py`: add `settings` table in `init_db()` + `get_setting`/`set_setting` helpers.
2. `drafts_api.py`: add `AUTO_GEN_SETTING` constant + `run_scheduled_generation()`.
3. `main.py`: swap the scheduler job to `run_scheduled_generation`; add toggle route +
   `_auto_gen_toggle_btn`; pass `auto_gen_enabled` to the drafts template.
4. `drafts_list.html`: add the toggle button.
5. Tests (below), then `cd backend && uv run pytest`.

## Tests Needed
Follow `.claude/rules/testing.md` (isolated `test_db` fixture, `admin_client`, mock Claude).
- **`tests/test_db.py`**: `settings` table exists after `init_db`; `get_setting` returns default
  when key absent; `set_setting` then `get_setting` round-trips; `set_setting` twice overwrites
  (upsert); `init_db` idempotent does not drop existing settings rows.
- **`tests/test_drafts.py`**:
  - `run_scheduled_generation` no-ops when flag default-OFF — returns `{"generated": 0,
    "skipped": True}`, no Claude call, no drafts created.
  - `run_scheduled_generation` generates when flag ON (`db.set_setting(...,"1")`, mock Claude → 1 draft).
  - **Req 4 guard:** `POST /api/drafts/generate` still returns 201 and generates while flag OFF.
  - Toggle route: unauthenticated `POST /admin/drafts/toggle-auto-gen` → 303 (auth guard);
    admin POST flips the stored value and returns button HTML containing "Auto: on"/"Auto: off".
  - `/admin/drafts` renders the toggle button reflecting current state (`b"Auto: off"` by default).

## Risks & Trade-offs
- **Body-guard wording vs req 4**: implemented as a scheduled wrapper (see Key design decision).
- **Default OFF on fresh prod deploy**: no drafts generated automatically until an admin flips
  the toggle on — the stated intent (req 5). Worth a one-line note in docs.
- **Persistence**: the flag lives in `blog.db` under `DB_DIR` (the `db_data` volume), so it
  survives deploys. Deleting `blog.db` resets it to OFF.
- **Concurrency**: single scheduler + occasional manual toggle — no SQLite locking concern.

## Critical Files
- backend/backend/db.py
- backend/backend/routers/drafts_api.py
- backend/backend/main.py
- backend/frontend/templates/drafts_list.html
- backend/backend/tests/test_drafts.py
