# Spec: Post Reactions

## Overview

Add a single lightweight reaction ("clap") readers can give a post without writing a
comment. Currently the only engagement signal on a post is a full comment — a real
barrier for readers who just want to acknowledge a post was useful. This adds a
public, no-auth `POST /api/posts/{slug}/react` endpoint that increments a counter, an
HTMX-driven button on `post.html`, and client-side (`localStorage`) deduplication so
the same browser can't spam the button — while accepting that this is a soft limit,
not a security boundary.

---

## Current State

**Database:** `posts` has no reaction-related column. The only post-engagement
columns today are `views` (page-load counter, see `post-view-counter.md`) and the
`comments` table (full-text, requires author + body).

**API:** `backend/routers/posts_api.py` defines the `posts` router
(`prefix="/api/posts"`) with `PostIn`/`PostOut` Pydantic schemas and the existing
admin-gated CRUD routes (`create_post`, `update_post`, `delete_post`,
`unpublish_post`), all using `Depends(_get_require_admin)` via the lazy-import helper
`_get_require_admin()`. There is also a non-router admin-gated endpoint in `main.py`
(`POST /api/posts/{slug}/toggle-ai-comments`) that follows a different pattern
(`Depends(require_admin)` imported directly) — the reaction endpoint belongs in
`posts_api.py` since it's a public, non-admin REST resource on `posts`, not an admin
toggle.

**Rate limiting:** `slowapi`'s `Limiter` instance (`limiter = Limiter(key_func=
get_remote_address)`) is created in `main.py` and attached to `app.state.limiter`. The
only existing use of `@limiter.limit(...)` is on the comment-submission route, defined
directly in `main.py` where `limiter` is in scope. `posts_api.py` is a separate module
and does not currently import `limiter` — this needs to change (see Implementation
Notes) or the rate limit needs to live in `main.py` instead of the router.

**Post page template:** `post.html` renders the article, then (if present) a Sources
section, then a Related Posts section, then includes `comments_section.html` inside
`<section id="comments-section">`. There is no existing slot between Sources and
Comments.

---

## Files to Modify

| File | Reason |
|------|---------|
| `backend/db.py` | Add `reactions INTEGER NOT NULL DEFAULT 0` column migration to `posts`; include it in `row_to_dict()` (already included automatically since it does `dict(row)`) |
| `backend/routers/posts_api.py` | Add `POST /{slug}/react` endpoint, rate-limited, no auth; add `reactions` to `PostOut` |
| `frontend/templates/post.html` | Add reaction button section between Sources and Comments |
| `backend/main.py` | No context changes needed — `post` route already passes the full `article` dict (which will include `reactions` once `row_to_dict` picks it up) to the template |
| `backend/tests/test_api.py` | Tests for the react endpoint |
| `backend/tests/test_routes.py` | Test that `post.html` renders the reaction button with the current count |

## Files to Create

None. The endpoint goes in the existing `posts_api.py`; no new template partial is
needed since the button is a small, self-contained block.

---

## Implementation Notes

### `backend/db.py` — migration

Add alongside the existing `cols` migration checks in `init_db()`:

```
if "reactions" not in cols:
    conn.execute("ALTER TABLE posts ADD COLUMN reactions INTEGER NOT NULL DEFAULT 0")
```

No changes needed to `row_to_dict()` — it does `d = dict(row)` first, so any new
column is automatically included without explicit handling (same as how `views` is
already passed through).

### `backend/routers/posts_api.py` — endpoint

Add `reactions: int = 0` to `PostOut` so `GET /api/posts` and `GET /api/posts/{slug}`
return the count alongside other fields (useful for any future external consumer,
even though the HTML page reads it via `row_to_dict` directly).

New endpoint:

```
POST /api/posts/{slug}/react
```

- No `Depends(_get_require_admin)` — explicitly public.
- Looks up the post by slug; 404 if not found (`HTTPException(404, "Post not found")`,
  matching the existing error message convention in this file).
- `UPDATE posts SET reactions = reactions + 1 WHERE slug = ?` (atomic increment, same
  pattern as the views counter).
- Returns `{"reactions": N}` — a plain dict response, not a full `PostOut`, since the
  client only needs the updated count to swap into the DOM.
- Rate limit: 3/minute per IP. Since `limiter` lives in `main.py` and `posts_api.py`
  must not import from `main.py` (that would invert the dependency direction the
  architecture rules establish — `main.py` imports routers, not the reverse), import
  `slowapi`'s `Limiter` pattern independently: either (a) move `limiter` into a small
  shared module (e.g. `backend/rate_limit.py`) that both `main.py` and `posts_api.py`
  import, or (b) construct the rate limit check inline using `slowapi`'s `Limiter`
  keyed the same way. Option (a) is cleaner and reusable for future endpoints — add
  `backend/rate_limit.py` exporting `limiter = Limiter(key_func=get_remote_address)`,
  update `main.py` to import it from there instead of constructing its own, and have
  `posts_api.py` import the same instance. This is a small refactor of where `limiter`
  lives, not a behavior change for the existing comment rate limit.

### `frontend/templates/post.html` — reaction button

Insert a new section after the Sources block (or after the article if no sources) and
before the Related Posts / Comments sections:

```
{% if post.sources %}
... existing sources section ...
{% endif %}

<!-- new: reaction section -->
<section class="mt-12 pt-8 border-t border-zinc-800/60 flex items-center gap-3">
  <button id="react-btn"
          hx-post="/api/posts/{{ post.slug }}/react"
          hx-swap="none"
          class="reaction-btn">
    👍 <span id="react-count">{{ post.reactions }}</span>
  </button>
</section>
```

Button states (CSS classes, not literal markup above):
- **Normal** (not yet reacted in this browser): indigo outline, default cursor.
- **Reacted** (matching `localStorage` key found): filled indigo background, `disabled`
  visual appearance (lower opacity, `cursor: default`) — but not an actual `disabled`
  attribute, since HTMX still needs the element present; the dedup is enforced by a
  small inline script checking `localStorage`, not by disabling the button outright
  (a determined user can still click it again from devtools — acceptable, see Risks).

Client-side script (in the same template, or appended to `post-enhancements.js` per
the existing convention of IIFE-wrapped page scripts — `post-enhancements.js` is
already loaded in `base.html` and is the natural home for this rather than inline
`<script>` in `post.html`):
- On page load, check `localStorage.getItem('reacted_{{ post.slug }}')`. If present,
  apply the "reacted" visual class immediately (skip the round trip).
- On successful HTMX response (`htmx:afterRequest` for `#react-btn`), parse the
  `{"reactions": N}` response, update `#react-count` text, set
  `localStorage.setItem('reacted_<slug>', '1')`, and apply the "reacted" class.
- The button is NOT hidden or removed after reacting — clicking again still POSTs
  (server has no hard limit either) but the visual state communicates "you already
  did this" to discourage repeat clicks.

### `backend/main.py`

No route changes required. The `GET /blog/{slug}` handler already passes `article`
(built via `get_post_by_slug` → `row_to_dict`) into the `post.html` context as `post`,
so `post.reactions` becomes available automatically once the column exists.

---

## Risks & Trade-offs

1. **No real anti-abuse protection.** `localStorage` dedup is trivially bypassed
   (incognito window, clearing storage, different browser, curl). Combined with a
   3/minute per-IP rate limit, the worst case is a slow trickle of inflated counts,
   not a meaningful integrity guarantee. This is acceptable for a vanity metric — it
   is explicitly not meant to gate anything (no rewards, no ranking algorithm depends
   on exact precision).

2. **Rate limit granularity (3/minute per IP) only meaningfully restricts a single
   browser/IP hammering the endpoint; it does not stop one-reaction-per-post-per-IP
   abuse across many posts in the same minute.** Tightening further risks
   false-positives behind shared/corporate NAT IPs reacting to different posts
   legitimately. 3/minute is a reasonable compromise, not a precise control.

3. **`hx-swap="none"` means the count update must be handled in JS, not HTMX's normal
   declarative swap.** This is necessary because the response is a tiny JSON payload
   (`{"reactions": N}`), not HTML — matching the existing pattern in this codebase
   where API endpoints return JSON and HTML page glue lives separately (the
   `toggle-ai-comments` endpoint, by contrast, returns HTML directly for an
   `hx-swap="outerHTML"`; reactions intentionally don't follow that pattern because
   the response also needs to drive `localStorage`, which requires JS regardless).

4. **Shared `limiter` instance refactor (`backend/rate_limit.py`) touches `main.py`
   import wiring.** Low risk — it's a pure extraction with no behavior change to the
   existing comment-rate-limit test coverage, but it does mean this feature's
   implementation isn't fully contained to `posts_api.py` alone.

---

## Tests Needed

`backend/tests/test_api.py`:

```
test_react_endpoint_returns_200
test_react_endpoint_increments_count
test_react_endpoint_returns_updated_count_in_body
test_react_twice_increments_twice_no_409
test_react_unknown_slug_returns_404
test_react_rate_limited_after_three_per_minute
test_post_out_includes_reactions_field
```

`backend/tests/test_routes.py`:

```
test_post_page_renders_reaction_button
test_post_page_reaction_button_shows_current_count
```

`backend/tests/test_db.py`:

```
test_init_db_adds_reactions_column_with_default_zero
```

---

## Critical Files

- `backend/db.py` — `reactions` column migration
- `backend/routers/posts_api.py` — `react` endpoint, `PostOut.reactions`
- `backend/rate_limit.py` (new, extracted from `main.py`) — shared `Limiter` instance
- `frontend/templates/post.html` — reaction button markup
- `frontend/static/js/post-enhancements.js` — localStorage dedup + count swap logic
- `backend/tests/test_api.py` — endpoint test coverage
