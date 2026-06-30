# Spec: Post Series / Collections

## Overview

Let related posts be grouped into an ordered series (e.g. a 4-part deep dive) so
readers can navigate between parts and discover that a post is part of a larger
collection. Today posts are only ever connected by tags (a loose, many-to-many,
unordered relationship via `get_related_posts()`'s tag-overlap scoring) — there is no
way to express "read these N posts in this specific order." This adds a `series`
table, series assignment fields on `posts`, a small admin CRUD surface, and a
prev/next navigation strip on the post page.

---

## Current State

**Database:** No `series` concept exists anywhere. `posts.tags` (JSON array) is the
only grouping mechanism, consumed by `get_related_posts()` in `data/posts.py` (pure
overlap-count scoring, no ordering).

**Admin surface:** Existing admin pages follow a consistent pattern — `main.py` hosts
the HTML routes (`/admin/posts`, `/admin/topics`, etc.) directly, each backed by a
template extending `base.html`'s `{% block content %}`, with create/edit/delete via
plain HTML forms (`Form(...)` params, not JSON) posting back to `main.py` routes that
`RedirectResponse` afterward — this is distinct from the `/api/*` JSON routers, which
exist in parallel for programmatic/REST access. Per `.claude/rules/architecture.md`,
"if a new admin section grows large, extract to a router" — series admin is small
enough (list/create/delete + an assignment dropdown bolted onto the existing
`/admin/posts` edit flow) to start as routes in `main.py`, matching how topics and
comments admin are currently handled, while the REST CRUD lives in its own new router
per the "New REST resource → new `routers/<name>_api.py`" rule.

**`/admin/posts` page:** Not read in detail for this spec, but per the architecture
docs it's the admin posts listing — assigning a post to a series happens on its edit
flow, which this spec extends with a series dropdown + order field.

**Post page (`post.html`):** Currently has no series-related UI. The header (title,
tags, date, reading time) is followed directly by the optional hero image, summary
card, and content body.

**Blog list (`blog.html`):** Post cards show date, reading time, title, summary, tags
— no series indicator.

---

## Files to Modify

| File | Reason |
|------|---------|
| `backend/db.py` | Add `series` table; add `series_id` + `series_order` columns to `posts` |
| `backend/main.py` | `/admin/series` HTML routes (list/create/delete); extend post edit flow with series assignment; `GET /blog/{slug}` fetches series siblings for nav strip |
| `frontend/templates/post.html` | Series nav strip (Part N of M, prev/next links) below header |
| `frontend/templates/blog.html` | Small "Part N" badge on post cards belonging to a series |
| `frontend/templates/admin_posts.html` | Series assignment control on the post edit form (or a per-row indicator + link to assign) |
| `backend/routers/posts_api.py` | `PATCH /{slug}/series` — assign series + order (only this one series-related action lives here since it operates on a `posts` row) |
| `backend/data/posts.py` | New helper(s) to fetch series siblings ordered by `series_order` |

## Files to Create

| File | Reason |
|------|---------|
| `backend/routers/series_api.py` | REST CRUD for the `series` resource itself: `GET /api/series`, `POST /api/series`, `DELETE /api/series/{id}` |
| `frontend/templates/admin_series.html` | Admin page: list existing series, create-new form, delete buttons |
| `backend/tests/test_series.py` | New test module per the "test file mirrors module" convention |

---

## Implementation Notes

### `backend/db.py` — schema

New table:

```
CREATE TABLE IF NOT EXISTS series (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL
)
```

`id` is a slug-style text PK (e.g. derived from title via the existing `_slugify()`
pattern already duplicated across `posts_api.py` and `topics_api.py` — reuse one of
those rather than writing a third copy; `topics_api._slugify` is already imported into
`main.py`, so the series admin route in `main.py` can reuse it directly).

New columns on `posts`, added via the existing migration-check pattern in `init_db()`:

```
if "series_id" not in cols:
    conn.execute("ALTER TABLE posts ADD COLUMN series_id TEXT REFERENCES series(id)")
if "series_order" not in cols:
    conn.execute("ALTER TABLE posts ADD COLUMN series_order INTEGER")
```

SQLite doesn't enforce `REFERENCES` constraints unless `PRAGMA foreign_keys = ON` is
set (it isn't, anywhere in this codebase currently) — the `REFERENCES` clause here is
documentation, not enforcement. Deleting a series with posts still assigned to it will
leave those posts with a dangling `series_id`; the deletion endpoint must explicitly
null out `series_id`/`series_order` on affected posts rather than relying on cascade
behavior that doesn't exist (see below).

`row_to_dict()` needs no changes — `series_id` and `series_order` pass through via the
existing `dict(row)` spread; `series_order` may be `None` for posts not in a series,
which templates must guard against (`{% if post.series_id %}`).

### `backend/routers/series_api.py` — new router

Mirrors the structure of `topics_api.py` (standalone, no cross-router imports per the
dependency-direction rule):

```
router = APIRouter(prefix="/api/series", tags=["series"])
```

- `GET /api/series` — list all series, each with a computed `post_count` (join/count
  against `posts.series_id`), no auth required (read-only, public-safe metadata).
- `POST /api/series` — admin-gated (`Depends(_get_require_admin)`, same lazy-import
  pattern as `posts_api.py`/`comments_api.py`). Body: `{title, description}`. `id`
  auto-derived via `_slugify(title)`, with the same disambiguation-on-collision
  pattern used in `main.py`'s `admin_topic_create` (`if id exists: append a counter`).
- `DELETE /api/series/{id}` — admin-gated. Before deleting the `series` row, run
  `UPDATE posts SET series_id = NULL, series_order = NULL WHERE series_id = ?` to
  avoid leaving dangling references (no FK cascade exists, as noted above). Then
  delete the `series` row. 404 if the series doesn't exist.

`PATCH /api/posts/{slug}/series` lives in `posts_api.py` instead, not here, because it
mutates a `posts` row, consistent with this file's existing ownership of all
`posts`-row mutations (`update_post`, `unpublish_post`, the future `react` endpoint).
Body: `{series_id: str | None, series_order: int | None}` — passing `series_id: null`
unassigns the post from any series (sets both columns to `NULL`). Validates the
target series exists (404 if `series_id` is non-null but unknown) before assigning.

### `backend/main.py` — admin HTML routes + public nav data

**Admin series page**, following the existing `/admin/topics` pattern:
- `GET /admin/series` → `admin_series.html`, listing all series with post counts and
  a create form (same "list + inline create form + delete buttons" layout as
  `admin_topics.html`'s list view, not the topics' separate "new" page — series have
  only two fields, so a single-page list+form is simpler than `admin_topics.html`'s
  two-page list/edit split).
- `POST /admin/series` → create (delegates to the same logic as `series_api.py`'s
  POST, or simply redirects through it — simplest: this HTML route directly does the
  insert itself, matching how `admin_topic_create` does its own file write rather than
  calling into `topics_api.py`'s functions).
- `POST /admin/series/{id}/delete` → delete (same null-out-then-delete logic as
  `series_api.py`'s DELETE).

**Post edit flow** (`/admin/posts` — wherever the existing edit form lives, not fully
read for this spec but following the `admin_draft_edit` pattern of `Form(...)`
params): add a `series_id` select dropdown (populated from `GET /api/series` or a
direct query) and a `series_order` number input, submitted alongside the existing
title/summary/content/tags fields, applied via an `UPDATE posts SET series_id=?,
series_order=? WHERE slug=?` (or by calling the new `PATCH` endpoint).

**`GET /blog/{slug}` — series siblings:** after fetching `article`, if
`article["series_id"]` is set, query all posts sharing that `series_id` ordered by
`series_order ASC`, and compute: the post's own position (`N`), the total count
(`M`), and the immediately adjacent prev/next posts (by `series_order`) for direct
links. Add a helper in `data/posts.py` — `get_series_siblings(series_id: str) ->
list[dict]` — rather than inlining the query in `main.py`, consistent with how
`get_related_posts` is already factored out there. Pass `series` (the series row,
for its title) and `series_siblings` (ordered list) into the `post.html` context.

### `frontend/templates/post.html` — series nav strip

Below the existing header block (after the `<div class="flex items-center gap-3 ...">`
meta line, before the hero image), conditionally render:

```
{% if post.series_id %}
<div class="series-nav-strip">
  Part {{ series_siblings.index(post) + 1 }} of {{ series_siblings | length }} — {{ series.title }}
  [prev link if not first] [next link if not last]
</div>
{% endif %}
```

(Index computation is illustrative — in practice, compute `part_number` /
`total_parts` / `prev_post` / `next_post` in the route handler in `main.py` rather
than doing list-index math in the template, keeping Jinja logic minimal per this
codebase's existing style where templates mostly just iterate pre-shaped context
data.) Prev/next links use the standard HTMX nav attributes already used throughout
`post.html` for internal navigation (`hx-get`, `hx-target="#main-content"`,
`hx-select="#main-content"`, `hx-push-url="true"`, `hx-swap="innerHTML"`).

### `frontend/templates/blog.html` — series badge

In the post card loop (`{% for post in posts %}`), inside the existing tags row or
just above it, conditionally add a small badge when `post.series_id` is set:
`Part {{ post.series_order }}` (styled consistently with the existing `.tag` class
but visually distinct — e.g. an indigo-tinted variant — to differentiate it from
topic tags). Computing "Part N" here only needs `series_order` directly on the post
row already returned by `get_posts_page()` — no extra query needed for the blog list
view, unlike the post detail page which needs full sibling data for prev/next.

### `frontend/templates/admin_posts.html`

Add either an inline series indicator per row (badge + "assigned to: X" text) linking
to that post's edit form, or fold the series dropdown directly into the existing edit
form if `admin_posts.html` already has inline editing — exact placement depends on
the current (unread) structure of this template; flag for the implementer to check
the existing edit-row pattern (likely similar to `admin_draft_edit`'s `Form(...)`-based
update) before adding fields.

---

## Risks & Trade-offs

1. **No FK enforcement.** SQLite foreign keys are off by default in this codebase
   (`PRAGMA foreign_keys` is never set). The `REFERENCES series(id)` clause on
   `posts.series_id` is purely documentary. Series deletion must manually null out
   referencing posts (handled explicitly in both `series_api.py` and the
   `/admin/series` HTML route) — easy to forget if either deletion path is modified
   later without updating the other. Consider consolidating both deletion paths to
   call one shared helper function to avoid drift.

2. **`series_order` is a free-form integer, not auto-managed.** Two posts in the same
   series can end up with the same `series_order` (e.g. both set to `2`) with no
   uniqueness constraint. The "Part N of M" display and prev/next computation should
   tie-break deterministically (e.g. secondary sort by `date ASC`) rather than error,
   but duplicate orders will produce a confusing reading order. Acceptable for v1 —
   admin is trusted to assign sane ordering; a stricter implementation (auto-increment
   per series, reorder-on-insert) is a possible follow-up, not in scope here.

3. **Two admin surfaces for series mutation** (`/admin/series` HTML routes in
   `main.py` and `/api/series` JSON routes in `series_api.py`) duplicate
   create/delete logic, mirroring the existing duplication pattern between
   `admin_topic_create` (file-based) and... actually topics have no parallel
   `/api/topics` create duplication since `topics_api.py` IS the CRUD and `main.py`'s
   admin routes call into the same JSON file functions (`_load_topics`/
   `_save_topics`). Series should follow that same tighter pattern instead: have
   `main.py`'s `/admin/series` HTML routes call the same DB logic `series_api.py`
   defines (extract shared insert/delete logic into a plain function `series_api.py`
   exports, called by both the router's endpoint and `main.py`'s HTML route) rather
   than reimplementing the INSERT/DELETE SQL twice. This avoids the FK-enforcement
   drift risk in point 1 as a side effect.

4. **Post detail page now runs an extra query** (series siblings) on every
   `GET /blog/{slug}` for posts in a series — negligible cost at this scale (a single
   indexed `WHERE series_id = ?` lookup), only run conditionally when
   `article["series_id"]` is set.

---

## Tests Needed (`backend/tests/test_series.py`)

```
# Schema
test_init_db_creates_series_table
test_init_db_adds_series_id_column_to_posts
test_init_db_adds_series_order_column_to_posts

# Series CRUD
test_create_series_returns_201
test_create_series_slug_derived_from_title
test_create_series_slug_collision_appends_suffix
test_list_series_returns_all_with_post_counts
test_delete_series_returns_204
test_delete_series_nulls_out_assigned_posts
test_delete_nonexistent_series_returns_404

# Post assignment
test_assign_post_to_series_sets_series_id_and_order
test_assign_post_to_unknown_series_returns_404
test_unassign_post_from_series_sets_null
test_assign_nonexistent_post_returns_404

# Display
test_post_page_shows_series_nav_when_in_series
test_post_page_hides_series_nav_when_not_in_series
test_post_page_series_nav_shows_correct_part_number
test_post_page_series_nav_links_to_prev_and_next
test_blog_page_shows_part_badge_on_series_posts
test_blog_page_hides_part_badge_on_non_series_posts

# Admin pages
test_admin_series_page_lists_series
test_admin_series_create_form_creates_series
test_admin_series_delete_removes_series
```

---

## Critical Files

- `backend/db.py` — `series` table, `posts.series_id`/`series_order` columns
- `backend/routers/series_api.py` — series CRUD (new file)
- `backend/routers/posts_api.py` — `PATCH /{slug}/series` assignment endpoint
- `backend/main.py` — `/admin/series` routes, post edit series fields, `GET /blog/{slug}` sibling fetch
- `backend/data/posts.py` — `get_series_siblings()` helper (new function)
- `frontend/templates/post.html` — series nav strip
- `frontend/templates/blog.html` — Part N badge
- `frontend/templates/admin_series.html` — admin list/create page (new file)
- `backend/tests/test_series.py` — full coverage (new file)
