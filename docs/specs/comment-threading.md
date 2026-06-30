# Spec: Comment Threading

## Overview

Allow a single level of replies on comments so a reader (or the post author) can
respond directly to a specific comment instead of every comment being a flat,
unordered list. Today `comments` has no notion of a parent — every comment is
top-level, sorted only by `created_at ASC`. This adds a nullable `parent_id` column,
a "Reply" affordance per comment that expands an inline form, and grouped rendering
(top-level comments with their replies nested directly beneath) in both the public
post page and the admin comments list. Nesting is capped at one level — replies
cannot themselves be replied to.

---

## Current State

**Database:** `comments` has `id` (TEXT PK, UUID), `post_slug`, `author`, `body`,
`created_at`, `is_generated` (INTEGER, AI-comment flag), and `status` (TEXT, already
added by the AI-comment-workflow feature — `'published'` / `'generated'` /
`'approved'`, default `'published'`). `comment_row_to_dict()` in `db.py` converts
`created_at` to a `datetime`, `is_generated` to `bool`, and includes `status`. No
`parent_id` column exists.

**Comment creation flow (two distinct paths today):**
1. **Public/human comments** — `POST /blog/{slug}/comments` in `main.py`
   (`submit_comment`), rate-limited at `5/minute`, takes `author`/`body` as form
   fields (not JSON), validates length inline (not via Pydantic — this route doesn't
   use `CommentIn`), inserts directly with raw SQL
   (`is_generated=0`, implicit `status` default `'published'` since the column has a
   DB-level default and the INSERT's explicit column list — `id, post_slug, author,
   body, created_at, is_generated` — omits `status` entirely, relying on
   `DEFAULT 'published'`), then re-renders `comments_section.html` as an HTML
   fragment (HTMX target `#comments-section`, full-replace `innerHTML`).
2. **API/admin comments** — `POST /api/comments` in `comments_api.py`
   (`create_comment`), admin-gated, uses the `CommentIn` Pydantic model
   (`post_slug`, `author`, `body`), explicit `status='published'`. Returns JSON
   (`CommentOut`), not HTML — this is the REST surface, not the public form's target.

Both paths need `parent_id` support since both are valid ways a comment enters the
system, but only the public flow (`main.py`) needs the reply-form HTMX partial route,
since `/api/comments` is the JSON surface with no HTML rendering involved.

**Public display (`GET /blog/{slug}` in `main.py`):** queries `SELECT * FROM comments
WHERE post_slug = ? AND (status = 'published' OR is_generated = 0) ORDER BY
created_at ASC` — flat list, no grouping. The same query (and the same status filter)
is duplicated in `submit_comment` after insert. `comments_section.html` iterates
`comments` flatly, rendering each as a `.card` with author/date/body, followed by the
comment form.

**Admin display (`admin_comments.html` + `GET /admin/comments` in `main.py`):**
queries all comments (`ORDER BY created_at DESC`, no status filter — admin sees
everything), renders a flat list with AI/status badges and approve/publish/delete
actions per row.

---

## Files to Modify

| File | Reason |
|------|---------|
| `backend/db.py` | Add `parent_id TEXT REFERENCES comments(id)` column to `comments`; no change needed to `comment_row_to_dict()` (passes through automatically) |
| `backend/routers/comments_api.py` | Accept optional `parent_id` in `CommentIn`/`create_comment`; validate parent exists and is itself top-level; add `parent_id` to `CommentOut` |
| `backend/main.py` | `submit_comment` accepts optional `parent_id` form field with the same validation; both comment-fetch queries group by parent before rendering; new `GET /blog/{slug}/comments/{id}/reply-form` HTML partial route |
| `frontend/templates/comments_section.html` | Render top-level comments with their replies nested beneath; add "Reply" button per comment; add a target div for the inline reply form partial |
| `frontend/templates/admin_comments.html` | Indent replies under their parent; show "replying to {author}" context on reply rows |
| `backend/tests/test_comments.py` | New tests for parent validation, grouping, reply-form route |

## Files to Create

| File | Reason |
|------|---------|
| `frontend/templates/reply_form.html` | Small partial returned by the new reply-form HTMX route — a scoped-down version of the comment form in `comments_section.html`, with a hidden `parent_id` field |

---

## Implementation Notes

### `backend/db.py` — migration

Add to the existing `comment_cols` migration block in `init_db()`:

```
if "parent_id" not in comment_cols:
    conn.execute("ALTER TABLE comments ADD COLUMN parent_id TEXT REFERENCES comments(id)")
```

As with `post-series.md`'s `series_id`, SQLite foreign keys are not enforced
(`PRAGMA foreign_keys` is never turned on in this codebase) — the `REFERENCES` clause
is documentation only. Deleting a parent comment leaves orphaned replies with a
dangling `parent_id` unless explicitly handled (see Risks — `delete_comment` in
`comments_api.py` currently does a plain `DELETE FROM comments WHERE id = ?` with no
cascade).

`comment_row_to_dict()` needs no code change — `parent_id` passes through via the
existing `dict(row)` spread, will be `None` for all pre-existing and new top-level
comments.

### `backend/routers/comments_api.py` — schema + validation

Add `parent_id: str | None = None` to both `CommentIn` and `CommentOut`.

In `create_comment()`, after confirming the post exists and before inserting:
- If `body.parent_id` is provided, look up that comment
  (`SELECT * FROM comments WHERE id = ?`). 404 if not found
  (`HTTPException(404, detail=f"Parent comment '{body.parent_id}' not found")`).
- **Max one level of nesting**: if the looked-up parent itself has a non-null
  `parent_id`, reject with `HTTPException(400, detail="Cannot reply to a reply")` —
  this is the "reply-to-reply returns 400" requirement.
- Also validate the parent belongs to the same `post_slug` as the new comment — a
  `parent_id` pointing at a comment on a different post is a data-integrity bug, not
  a valid use case (400 if mismatched).
- Insert with `parent_id` included in the explicit column list (extending the existing
  `INSERT INTO comments (id, post_slug, author, body, created_at, is_generated,
  status) VALUES (...)` to add `parent_id`).

`list_comments` (`GET /api/comments?post_slug=X`) needs no structural change — it
already returns everything for a post in `created_at ASC` order; `parent_id` is just
an extra field in each returned object. Consumers that want grouping do it
client-side or via the HTML routes, which do the grouping server-side (see below).

### `backend/main.py` — public flow

**`submit_comment`** (`POST /blog/{slug}/comments`): add `parent_id: str | None =
Form(None)` parameter. Apply the same validation as `comments_api.py`'s
`create_comment` (parent exists, belongs to this `post_slug`, is not itself a reply)
— inline, matching this route's existing style of inline validation rather than
delegating to the router (these two comment-creation code paths already duplicate
validation logic today — e.g. author/body length checks exist independently in both
places — so duplicating the parent-validation rule here is consistent with, not a
regression from, the current pattern). On validation failure, raise the same
`HTTPException(400, ...)` style already used for author/body length errors in this
function. Include `parent_id` in the INSERT.

**Comment fetch + grouping** (duplicated today in both `post()` and
`submit_comment()` — extend both, or better, factor the existing duplicated query +
`comment_row_to_dict` mapping into a small helper since this feature adds real
grouping logic that would otherwise need to be duplicated a third time): after
fetching the flat list (same `status`/`is_generated` filter as today), partition into
`top_level = [c for c in comments if c["parent_id"] is None]` and build a
`replies_by_parent: dict[str, list[dict]]` from the rest. Pass both shapes (or a
single pre-nested structure — e.g. attach `c["replies"] = replies_by_parent.get(c["id"],
[])` directly onto each top-level comment dict) into the template context. Pre-nesting
in Python keeps `comments_section.html` simple (a single loop over top-level comments,
each rendering its own `replies` sub-list) rather than requiring Jinja to do the
grouping itself.

**New route — reply form partial:**

```
GET /blog/{slug}/comments/{comment_id}/reply-form
```

Looks up the comment by `id` (and matching `post_slug`, defense against cross-post
IDs), 404 if missing. Renders `reply_form.html` with `slug` and the parent
`comment_id` in context. This is a tiny, focused HTML fragment route — no rate
limiting needed since it doesn't write anything, just renders a form.

### `frontend/templates/comments_section.html`

Restructure the comment loop to render top-level comments, each followed by its
nested replies (using the pre-nested `c.replies` list from the route):

```
{% for c in comments %}
  <div class="card"> ... existing author/date/body markup ... </div>
  <button hx-get="/blog/{{ slug }}/comments/{{ c.id }}/reply-form"
          hx-target="#reply-form-{{ c.id }}"
          hx-swap="innerHTML"
          class="...">Reply</button>
  <div id="reply-form-{{ c.id }}"></div>

  {% for r in c.replies %}
    <div class="card ml-8"> ... same markup, indented, no Reply button ... </div>
  {% endfor %}
{% endfor %}
```

Replies render with the same card markup as top-level comments (author, date, body)
but indented (e.g. `ml-8` / a left border accent to visually group them under their
parent) and **without** their own "Reply" button — since replies cannot be replied to,
no affordance should suggest otherwise.

The reply-form target div (`#reply-form-{{ c.id }}`) starts empty; clicking "Reply"
HTMX-fetches `reply_form.html` into it. The form itself should support being
collapsed again (e.g. a "Cancel" link inside `reply_form.html` that does
`hx-get` back to nothing / uses `hx-on::after-request` to clear itself, or simpler:
re-toggling the Reply button swaps the div back to empty — exact UX left to
implementation, the structural requirement is just that the form is scoped to
`#reply-form-{{ c.id }}` so multiple comments' reply forms don't collide).

### `frontend/templates/reply_form.html` (new)

A scoped-down version of the existing comment form in `comments_section.html` —
`author` + `body` inputs, same `maxlength`/`required` constraints, but:
- `hx-post="/blog/{{ slug }}/comments"` (same endpoint as the main form)
- includes `<input type="hidden" name="parent_id" value="{{ comment_id }}">`
- `hx-target="#comments-section"` `hx-swap="innerHTML"` (same as the main form — a
  successful reply re-renders the whole comments section, which is simplest and
  consistent with how the top-level form already works, rather than trying to
  surgically inject just the new reply into the DOM)

### `frontend/templates/admin_comments.html`

Apply the same top-level/replies grouping (computed in `main.py`'s `admin_comments`
route, mirroring the public-side grouping helper) so replies render indented beneath
their parent in the admin list too. Each reply row additionally shows "replying to
{parent.author}" as small context text, since admin moderators reviewing a reply in
isolation need to know what it's responding to (the public page makes this visually
obvious via indentation; the admin list should make it explicit via text, since a
moderator scanning quickly benefits from not having to visually trace indentation
across a long list).

---

## Risks & Trade-offs

1. **No cascade delete for replies when a parent is deleted.** `DELETE
   /api/comments/{id}` in `comments_api.py` does a plain single-row delete. Deleting
   a parent that has replies leaves those replies with a `parent_id` pointing at a
   row that no longer exists — they'd vanish from the grouped public/admin views
   entirely (since the grouping logic looks up `replies_by_parent[c["id"]]` only for
   `id`s still present in the top-level set) even though the rows still exist in the
   DB, becoming permanently invisible orphans. **Decision needed at implementation
   time**: either (a) cascade-delete replies when their parent is deleted (extend
   `delete_comment` to also `DELETE FROM comments WHERE parent_id = ?`), or (b)
   promote orphaned replies to top-level on parent deletion (`UPDATE comments SET
   parent_id = NULL WHERE parent_id = ?`). Recommendation: cascade-delete (option a)
   — a reply without its parent's context is generally not meaningful standalone, and
   this matches the intuitive "delete this discussion" behavior an admin clicking
   Delete would expect.

2. **Two comment-creation code paths (`main.py`'s form-based route and
   `comments_api.py`'s JSON route) now both need parent-validation logic, and that
   logic is duplicated rather than shared** — consistent with pre-existing duplication
   in this codebase (author/body length validation is already separately implemented
   in both places) but means a future change to the nesting rule (e.g. allowing 2
   levels) requires updating both. Flagged, not solved — matches existing technical
   debt rather than introducing new debt.

3. **One-level cap is enforced at write time only, by checking the parent's own
   `parent_id`.** This is correct and sufficient — there's no recursive depth to
   worry about since a reply (a comment with non-null `parent_id`) can never become a
   valid parent (the check rejects replying to a comment that already has a
   `parent_id`), so depth is structurally bounded to 2 (top-level → reply) without
   needing a recursive CTE or depth counter.

4. **Pre-existing comments all get `parent_id = NULL` automatically** (new column,
   no default needed beyond SQLite's implicit `NULL` for an unspecified nullable
   column) — fully backward compatible, no backfill required, matches the spec's
   explicit requirement.

5. **Grouping logic duplicated between `post()`, `submit_comment()`, and
   `admin_comments()` in `main.py`** unless factored into a shared helper (e.g.
   `db.py::group_comments_by_parent(comments: list[dict]) -> list[dict]` or similar)
   — recommended to avoid three slightly-divergent copies of the same partition
   logic, especially since the public two (`post`, `submit_comment`) already
   duplicate the fetch query itself today.

---

## Tests Needed (`backend/tests/test_comments.py`)

```
# Schema
test_init_db_adds_parent_id_column
test_existing_comments_have_null_parent_id_by_default

# Creation via /api/comments
test_create_reply_with_valid_parent_id_succeeds
test_create_reply_includes_parent_id_in_response
test_create_reply_to_nonexistent_parent_returns_404
test_create_reply_to_a_reply_returns_400
test_create_reply_with_parent_on_different_post_returns_400
test_create_top_level_comment_parent_id_defaults_none

# Creation via POST /blog/{slug}/comments (public form)
test_submit_reply_form_with_parent_id_succeeds
test_submit_reply_to_a_reply_returns_400
test_submit_reply_to_nonexistent_parent_returns_404

# Reply-form partial route
test_reply_form_route_returns_200_for_valid_comment
test_reply_form_route_returns_404_for_unknown_comment
test_reply_form_includes_hidden_parent_id_field

# Display grouping
test_post_page_renders_reply_nested_under_parent
test_post_page_reply_has_no_reply_button
test_post_page_top_level_comment_has_reply_button
test_admin_comments_shows_replies_indented
test_admin_comments_shows_replying_to_context

# Deletion (cascade decision)
test_deleting_parent_comment_also_deletes_replies
```

---

## Critical Files

- `backend/db.py` — `parent_id` column migration
- `backend/routers/comments_api.py` — `parent_id` on `CommentIn`/`CommentOut`, validation in `create_comment`, cascade delete in `delete_comment`
- `backend/main.py` — `submit_comment` parent_id handling, comment grouping in `post()`/`submit_comment()`/`admin_comments()`, new reply-form route
- `frontend/templates/comments_section.html` — nested reply rendering, Reply button, reply-form target div
- `frontend/templates/reply_form.html` — new reply form partial
- `frontend/templates/admin_comments.html` — indented replies, "replying to" context
- `backend/tests/test_comments.py` — full coverage of validation, grouping, cascade
