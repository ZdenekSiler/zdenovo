# Spec: Blog Search

## Overview

Add full-text search across blog posts so readers can find a specific post by title,
summary, tags, or body content. Today the only ways to find a post are scrolling the
paginated `/blog` list or filtering by a single tag — there is no text search anywhere
in the app. This adds a SQLite FTS5 virtual table kept in sync with `posts` via
triggers, a search API endpoint, and an HTMX-powered search box in the sidebar and on
the `/blog` page.

---

## Current State

**Database:** `posts` is a plain table (`db.py`, `init_db()`), no FTS infrastructure
exists. SQLite's `sqlite3` module (Python stdlib) supports FTS5 as long as the SQLite
build it's linked against was compiled with FTS5 enabled — this is true for the
standard Python distributions on Linux/macOS used in this project's `uv` environment,
but is worth a one-time sanity check in CI/dev (see Risks).

**Posts API:** `backend/routers/posts_api.py` defines `router = APIRouter(prefix=
"/api/posts", tags=["posts"])` with `list_posts`, `get_post`, `create_post`,
`update_post`, `delete_post`, `unpublish_post`. A new `GET /search` route on this
router would resolve to `/api/posts/search` — but FastAPI route ordering matters: it
must be declared *before* `GET /{slug}` in the file, otherwise `/api/posts/search`
would be captured by the `{slug}` path parameter (slug="search") instead. This is the
single most important implementation detail for this feature.

**Sidebar / blog page:** `frontend/templates/base.html` defines a `{% block sidebar
%}` containing a profile card and a terminal widget; `blog.html` overrides this block
entirely to show the "Most Popular" widget instead (it does not call `{{ super() }}`),
meaning the blog page sidebar currently has no profile card — only popular posts. A
search widget needs to be added to `blog.html`'s sidebar override (not `base.html`,
since other pages like the homepage don't need a global search box per this spec's
scope) — but to keep `/blog/{slug}` (the post page) also searchable from the sidebar,
the same widget should be added inside `post.html`'s sidebar if it defines one, or
simply duplicated into the default `base.html` sidebar block. Decision: add the search
widget to `base.html`'s default sidebar (above the profile card), so it appears on
every page that doesn't override `{% block sidebar %}` (home, about, post, projects),
and also add it explicitly to the top of `blog.html`'s overridden sidebar block so it
isn't lost there. `blog.html` additionally gets an above-the-list search bar per the
spec's requirement, distinct from the sidebar widget.

---

## Files to Modify

| File | Reason |
|------|---------|
| `backend/db.py` | Create `posts_fts` FTS5 virtual table + sync triggers in `init_db()` |
| `backend/routers/posts_api.py` | Add `GET /search` endpoint (declared before `GET /{slug}`) |
| `frontend/templates/base.html` | Add sidebar search widget (input + results dropdown target) |
| `frontend/templates/blog.html` | Add search widget to overridden sidebar block; add search bar above the post list |
| `backend/tests/test_api.py` | Search endpoint tests |
| `backend/tests/test_db.py` | FTS5 table creation + trigger sync tests |

## Files to Create

None — search results render into an existing-pattern HTMX target; no new template
file is strictly required since the result list is a small enough fragment to inline
in `base.html`/`blog.html`. (If the dropdown markup ends up duplicated between the two
templates, consider extracting a `search_results.html` partial at implementation time
— flagged here as an option, not a requirement.)

---

## Implementation Notes

### `backend/db.py` — FTS5 table and sync triggers

After the existing `posts` table creation and column migrations in `init_db()`, add:

```
CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    slug UNINDEXED, title, summary, tags, content
)
```

`slug` is marked `UNINDEXED` since it's only needed to map a match back to the real
`posts` row, not to search against.

**Sync strategy:** use `CREATE TRIGGER IF NOT EXISTS` on `posts` for `AFTER INSERT`,
`AFTER UPDATE`, and `AFTER DELETE`, mirroring changes into `posts_fts`:
- `AFTER INSERT ON posts` → `INSERT INTO posts_fts (slug, title, summary, tags,
  content) VALUES (new.slug, new.title, new.summary, new.tags, new.content)`
- `AFTER UPDATE ON posts` → since FTS5 doesn't support `UPDATE ... WHERE` against
  arbitrary non-rowid keys cleanly when the table has no explicit rowid alignment to
  `posts`, the simplest correct approach is `DELETE FROM posts_fts WHERE slug =
  old.slug` followed by the same `INSERT` as above with `new.*` — two statements in
  the same trigger body.
- `AFTER DELETE ON posts` → `DELETE FROM posts_fts WHERE slug = old.slug`.

**Backfill:** existing databases (created before this migration runs) already have
rows in `posts` with no corresponding `posts_fts` entries, and triggers only fire on
future writes. After creating the table and triggers, run a one-time backfill guarded
by an emptiness check: `INSERT INTO posts_fts (slug, title, summary, tags, content)
SELECT slug, title, summary, tags, content FROM posts WHERE slug NOT IN (SELECT slug
FROM posts_fts)` — safe to run on every `init_db()` call since it's a no-op once
synced (idempotent, unlike a blind `INSERT ... SELECT *` which would duplicate rows
on every restart).

Note: `tags` is stored as a JSON array string (e.g. `["python", "fastapi"]`) — FTS5
will tokenize the raw JSON text including brackets/quotes, which is acceptable (a
search for `python` will still match) but means searching for the literal substring
`"python"` with quotes would behave oddly. Not a real-world concern for this feature's
use case; not worth a separate denormalized tags column for v1.

### `backend/routers/posts_api.py` — search endpoint

```
GET /api/posts/search?q=<query>
```

**Must be declared above `get_post(slug: str)`** in the file (FastAPI matches routes
in declaration order; `/{slug}` is a catch-all for any single path segment under
`/api/posts/` and would otherwise shadow `/search`).

Behavior:
- Empty or whitespace-only `q` → return `[]` immediately, no query executed. This
  matches the spec requirement ("empty query returns empty results, not all posts")
  and avoids `MATCH ''` raising an FTS5 syntax error.
- Sanitize input before constructing the FTS5 `MATCH` query: strip FTS5 operator
  characters reserved for the query syntax (`"`, `*`, `^`, `:`, parentheses, `-` at
  token start) since user input is not meant to act as raw FTS5 query syntax — a
  reader typing `foo OR bar` should search for the literal phrase, not invoke FTS5
  boolean operators. The simplest safe approach: wrap the sanitized term(s) in double
  quotes and append `*` per-token for prefix matching (e.g. input `pyth` → FTS5 query
  `"pyth"*`), after stripping any embedded double quotes from the raw input to avoid
  breaking out of the quoted phrase.
- Query: `SELECT slug FROM posts_fts WHERE posts_fts MATCH ? ORDER BY rank LIMIT 10`,
  then fetch full rows for those slugs from `posts` (preserving FTS5's rank order,
  not `posts`' default date order — e.g. `SELECT * FROM posts WHERE slug IN (...)`
  result rows need to be re-ordered in Python to match the FTS5 rank sequence, since
  SQL `IN` does not guarantee result order).
- Returns the same shape as `GET /api/posts` (`list[PostOut]`) — reuses `row_to_dict`
  from `db.py`, consistent with every other route in this file.

### `frontend/templates/base.html` — sidebar search widget

Add near the top of the default `{% block sidebar %}` content (before the profile
card), an HTMX-powered search input:

```
<div class="border border-zinc-800/60 rounded-xl bg-zinc-900/40 p-4 relative">
  <input type="search" name="q" placeholder="Search posts..."
         hx-get="/api/posts/search"
         hx-trigger="input changed delay:300ms"
         hx-target="#search-results"
         hx-swap="innerHTML"
         class="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm ...">
  <div id="search-results" class="absolute ... mt-1 ... hidden-until-populated"></div>
</div>
```

Since the API returns JSON (`list[PostOut]`), not HTML, this HTMX call cannot render
directly — either (a) add a second, HTML-returning endpoint/response variant, or (b)
have the JSON endpoint double as the HTMX target by content-negotiating: return HTML
when the request has the `HX-Request` header, JSON otherwise. Per the architecture
rule "don't blend the two surfaces" (HTML routes return templates, API routes return
Pydantic models), the cleaner fit is to keep `GET /api/posts/search` JSON-only and add
a small HTML-rendering route for the dropdown — e.g. `GET /blog/search` in `main.py`
(HTML surface) that internally calls the same query logic and renders a
`TemplateResponse` fragment (title + date per result, linking to `/blog/{slug}` with
the existing HTMX nav attributes `hx-get`/`hx-target="#main-content"`/`hx-select=
"#main-content"`/`hx-push-url="true"`). The sidebar widget's `hx-get` then points to
`/blog/search`, not `/api/posts/search` — the latter remains the pure JSON API for
external/programmatic use, the former is the page-glue HTML route, consistent with how
`comments_section.html` is returned by `POST /blog/{slug}/comments` (an HTML page
route, not part of `/api/comments`). Update the "Files to Modify" implication: this
means `main.py` also needs a new small route, not just `posts_api.py` — call this out
explicitly so `/implement` doesn't miss it.

Dropdown rendering: each result is `title` (linked, navigates via the standard HTMX
nav pattern) + `date | dateformat`, shown below the input, hidden when empty.

### `frontend/templates/blog.html` — sidebar + above-list search bar

Since `blog.html` overrides `{% block sidebar %}` without `{{ super() }}`, duplicate
the same search widget markup at the top of its sidebar override (above "Most
Popular"). Additionally add a search bar above the post list in `{% block content %}`,
same `hx-get="/blog/search"` wiring but targeting a results area that replaces (or
sits above) `#posts-list` — simplest implementation: same dropdown-below-input pattern
as the sidebar, not a full list replacement, to avoid juggling pagination state when a
search is active.

---

## Risks & Trade-offs

1. **FTS5 availability is a build-time SQLite feature, not guaranteed on every Python
   install.** If the deployed environment's SQLite lacks FTS5, `CREATE VIRTUAL TABLE
   ... USING fts5` raises at `init_db()` time, breaking app startup entirely. Mitigate
   by checking the Hetzner production image's Python/SQLite build before merging (a
   `python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL
   TABLE t USING fts5(x)')"` smoke check) — flagged as a pre-implementation
   verification step, not solved by this spec alone.

2. **Mixing a JSON API route (`/api/posts/search`) with an HTML page-glue route
   (`/blog/search`) for the same underlying query duplicates query logic across two
   files** (`posts_api.py` and `main.py`) unless factored into a shared helper (e.g.
   `data/posts.py::search_posts(q: str) -> list[dict]`) that both call. Recommended:
   put the FTS5 query + sanitization in `data/posts.py` (consistent with its existing
   role as "read-only query helper for HTML pages" per the architecture rules) and
   have both `posts_api.py`'s `/search` and `main.py`'s `/blog/search` call it —
   avoids logic drift between the two surfaces.

3. **Trigger-based sync adds a small write-amplification cost** to every `posts`
   insert/update/delete (now also writes to `posts_fts`). Negligible at this blog's
   scale (dozens to low hundreds of posts), not a concern.

4. **Sanitization approach (stripping FTS5 special characters) is conservative and
   may reject legitimately useful queries** (e.g. someone searching for a quoted
   phrase). Acceptable trade-off — favors not crashing on malformed FTS5 syntax over
   supporting power-user query operators.

5. **Backfill `INSERT ... WHERE NOT IN` runs on every `init_db()` call.** At this
   scale it's cheap, but it's a linear scan of `posts_fts` on every app startup. Fine
   for the current post volume; would need revisiting only at a much larger scale.

---

## Tests Needed

`backend/tests/test_db.py`:

```
test_init_db_creates_posts_fts_table
test_init_db_backfills_existing_posts_into_fts
test_insert_post_syncs_to_fts_via_trigger
test_update_post_syncs_to_fts_via_trigger
test_delete_post_removes_from_fts_via_trigger
test_init_db_is_idempotent_does_not_duplicate_fts_rows
```

`backend/tests/test_api.py`:

```
test_search_returns_matching_posts_by_title
test_search_returns_matching_posts_by_content
test_search_returns_matching_posts_by_tag
test_search_empty_query_returns_empty_list
test_search_whitespace_query_returns_empty_list
test_search_sanitizes_fts5_special_characters
test_search_respects_limit_of_10
test_search_results_ordered_by_rank
```

`backend/tests/test_routes.py`:

```
test_blog_search_route_returns_html_fragment
test_sidebar_search_widget_present_on_blog_page
test_sidebar_search_widget_present_on_post_page
```

---

## Critical Files

- `backend/db.py` — FTS5 table, sync triggers, backfill
- `backend/data/posts.py` — shared `search_posts()` helper (new function)
- `backend/routers/posts_api.py` — `GET /api/posts/search` (JSON), declared before `GET /{slug}`
- `backend/main.py` — `GET /blog/search` (HTML fragment for HTMX dropdown)
- `frontend/templates/base.html` — sidebar search widget
- `frontend/templates/blog.html` — sidebar search widget duplicate + above-list search bar
- `backend/tests/test_db.py` — FTS5 trigger sync coverage
