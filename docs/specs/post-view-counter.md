# Spec: Post View Counter

## Overview

Make `posts.views` reflect real-time traffic instead of relying solely on the periodic
Cloudflare analytics sync, and surface the view count on the post page itself (it
currently only appears in the blog sidebar). Today a reader can visit a post 50 times
and the number won't move until the next `refresh_popular_posts()` cron tick (up to 8
hours later, and not at all if Cloudflare credentials aren't configured). This feature
adds a direct, in-app increment on page view so the counter is live and works even
without Cloudflare configured, while avoiding inflation from bots and crawlers.

---

## Current State

**Database:** `posts.views` is an `INTEGER NOT NULL DEFAULT 0` column (added by an
existing migration in `db.py`). Nothing in the app writes to it directly today.

**Existing view-count pipeline:** `backend/data/analytics.py::refresh_popular_posts()`
queries the Cloudflare GraphQL API for `/blog/{slug}` path hit counts over the trailing
30 days and does `UPDATE posts SET views = ? WHERE slug = ?` (an absolute overwrite, not
an increment). It is called once at startup (`lifespan` in `main.py`) and on a cron
schedule (`6,14,22` UTC daily). If `CLOUDFLARE_API_TOKEN` / `CF_ZONE_ID` aren't set, it
logs and returns 0 — `views` stays frozen at whatever the last successful sync wrote
(or 0 for a fresh DB).

**Already implemented (do not duplicate):**
- `data/posts.py::get_popular_posts()` already sorts by `views DESC, date DESC` — the
  prompt's request to "switch popular posts to sort by views from DB" is already done.
- `blog.html` sidebar already renders `{{ p.views }} views` when `p.views > 0`.

**Missing:**
- No increment happens when a real visitor loads `GET /blog/{slug}` in `main.py`.
- `post.html` (the post page itself) does not display the view count anywhere — only
  the blog sidebar does.
- No `format_views` filter exists; `blog.html` prints the raw integer.
- No distinction between this app-level counter and the Cloudflare-sourced number — they
  will both write to the same column, which needs an explicit reconciliation rule (see
  Risks).

---

## Files to Modify

| File | Reason |
|------|---------|
| `backend/main.py` | Increment `views` in `GET /blog/{slug}` (bot-filtered); register `format_views` Jinja filter |
| `backend/data/analytics.py` | Change `refresh_popular_posts()` from overwrite to "take the max" so it never regresses the live in-app counter |
| `frontend/templates/post.html` | Show `{{ post.views | format_views }} reads` in the header meta line |
| `frontend/templates/blog.html` | Apply `format_views` filter to the existing `{{ p.views }} views` sidebar line |
| `backend/tests/test_routes.py` | New tests for increment behavior, bot exclusion, and display |
| `backend/tests/test_data.py` or `backend/tests/test_db.py` | Test for `format_views` filter formatting boundaries |

## Files to Create

None. All changes fit within existing files.

---

## Implementation Notes

### `backend/main.py` — increment on view

In the `GET /blog/{slug}` handler (`async def post(request: Request, slug: str)`),
after confirming `article is not None`, check the request's `User-Agent` header. Treat
it as a bot if the (lower-cased) string contains any of `googlebot`, `bot`, `crawler`,
`spider`. An empty/missing User-Agent should also be treated as non-human and excluded
— curl and most simple scripts send no UA or a generic one, and counting those defeats
the purpose of a "reads" counter.

If not a bot, run `UPDATE posts SET views = views + 1 WHERE slug = ?` in the same
`get_conn()` block already used to fetch comments (or a separate short one — either is
fine since SQLite serializes writes). This must happen on every successful page load,
including repeat visits from the same reader — there is no session-based dedup in this
feature (see Risks: this is a "page loads" counter, not "unique visitors").

Order of operations matters: increment *after* confirming the post exists (404s should
never increment), and increment using `slug`, not the already-fetched `article["views"]`
value, to avoid a read-modify-write race — `views = views + 1` is atomic in SQLite.

Add the Jinja filter near the existing `dateformat` filter registration:

```
def _fmt_views(n: int) -> str:
    ...
templates.env.filters["format_views"] = _fmt_views
```

Format rule: values `< 1000` render as the plain integer (`"342"`); values `>= 1000`
render as one decimal place with a `k` suffix (`"1.2k"`, `"12.4k"`), following standard
truncation (not rounding) to avoid a `999 -> 1.0k` jump right at the boundary — clarify
with a concrete example: 1,250 views → `"1.2k"` (not `"1.3k"`).

### `backend/data/analytics.py` — non-regressing sync

Because the in-app counter now increments continuously between Cloudflare sync runs,
the existing `UPDATE posts SET views = ? WHERE slug = ?` would silently roll the
counter *backward* whenever Cloudflare's 30-day window total is lower than what the
app has already counted (e.g. right after a deploy resets the window, or for a post
older than 30 days where Cloudflare stops reporting it but the in-app counter keeps
climbing). Change the query to `UPDATE posts SET views = MAX(views, ?) WHERE slug = ?`
so the sync can only push the count up, never down. This also means the two sources
are blended into one number rather than precisely tracking either — acceptable per
the Risks section below.

### `frontend/templates/post.html` — display

In the header meta line (`<div class="flex items-center gap-3 text-xs text-zinc-600
pb-6 ...">` containing author / date / reading time), append a fourth segment after
reading time, separated by the existing `<span class="text-zinc-800">·</span>`
divider pattern already used between the other three items:

```
<span>{{ post.views | format_views }} reads</span>
```

Only render this segment if `post.views > 0`, matching the existing
`{% if p.views > 0 %}` guard pattern already used in `blog.html`'s sidebar — a post
with 0 views (e.g. a moment after publish) shouldn't show "0 reads".

### `frontend/templates/blog.html` — apply filter

Change the existing `{{ p.views }} views` line (inside the `{% if p.views > 0 %}`
block in the sidebar's `Most Popular` widget) to `{{ p.views | format_views }} views`.
No structural change — this is a one-line filter application.

---

## Risks & Trade-offs

1. **Not a unique-visitor counter.** Every page load increments, including repeat
   visits, refreshes, and back-button navigation. This is intentional and matches the
   "reads" framing rather than "unique readers" — adding session/IP dedup would require
   either a cookie or a separate `post_views` log table, which is more state than this
   feature's value justifies. If unique counting is wanted later, it's a separate spec.

2. **Bot filtering is a denylist, not a robust bot-detection system.** Sophisticated
   scrapers that spoof a normal browser UA will still count. This is a pragmatic
   filter for the common case (search engine crawlers, basic scripts), not a security
   control.

3. **HTMX partial navigation still re-triggers a full route call.** Because the sidebar
   nav uses `hx-get` + `hx-select="#main-content"` rather than client-side routing,
   navigating to a post via HTMX still hits `GET /blog/{slug}` server-side and
   increments normally — no special-casing needed.

4. **Two writers to the same column.** The in-app increment and the Cloudflare sync
   both write `posts.views`. The `MAX()` reconciliation avoids regressions but means
   the number is neither a pure in-app count nor a pure Cloudflare count — it's
   whichever is higher. Acceptable because the column's purpose (sort signal +
   approximate "popular" indicator) doesn't require source-level precision.

5. **No backfill for existing posts.** Posts that have never had a Cloudflare sync run
   and have zero in-app visits since this change ships will show 0 / no badge until
   traffic arrives. No migration needed — this is expected cold-start behavior.

---

## Tests Needed (`backend/tests/test_routes.py`)

```
test_visiting_post_increments_view_count
test_visiting_post_twice_increments_twice
test_visiting_nonexistent_post_does_not_increment
test_bot_user_agent_does_not_increment_googlebot
test_bot_user_agent_does_not_increment_generic_bot_substring
test_missing_user_agent_does_not_increment
test_post_page_shows_view_count_when_nonzero
test_post_page_hides_view_count_when_zero
```

`backend/tests/test_data.py` (or a new small filter test module):

```
test_format_views_below_1000_renders_raw_integer
test_format_views_at_1000_renders_with_k_suffix
test_format_views_truncates_not_rounds
```

`backend/tests/test_db.py` or `test_data.py`:

```
test_refresh_popular_posts_does_not_decrease_existing_views
```

---

## Critical Files

- `backend/main.py` — increment logic in `GET /blog/{slug}`, `format_views` filter registration
- `backend/data/analytics.py` — `MAX()` reconciliation in `refresh_popular_posts()`
- `frontend/templates/post.html` — view count display in header meta line
- `frontend/templates/blog.html` — `format_views` filter applied to sidebar
- `backend/tests/test_routes.py` — increment + bot-exclusion tests
