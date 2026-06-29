# Spec: AI Comment Workflow

## Overview

Add a lifecycle workflow for AI-generated comments: **Generated → Approved → Published**.

Currently, AI comments are inserted directly into the database with `is_generated=1` and immediately appear on the public blog alongside real comments. There is no review step. This feature adds a `status` column to the `comments` table so the admin can review, approve, and publish AI comments before they become visible to readers. Real (human) comments remain unaffected — they are always visible immediately. The per-post `ai_comments` toggle (already exists as a column on `posts`) continues to control whether AI comment generation runs for that post.

---

## Current State

**Database:** The `comments` table has columns: `id`, `post_slug`, `author`, `body`, `created_at`, `is_generated`. No `status` column exists. The `posts` table has an `ai_comments` INTEGER column (0/1) that controls whether the scheduler generates AI comments for a given post.

**Generation flow:** `CommentGenerator.generate_and_insert()` in `comments_api.py` inserts AI comments directly with `is_generated=1`. The scheduler (`generate_pending_comments()`) runs every 3 days.

**Public display:** `GET /blog/{slug}` queries ALL comments for the post with no filtering by status.

**Admin UI:** `/admin/comments` shows all comments with AI badges and delete buttons. The per-post `ai_comments` toggle is on `/admin/posts` (HTMX button calling `POST /api/posts/{slug}/toggle-ai-comments`).

---

## Files to Modify

| File | Reason |
|------|---------|
| `backend/db.py` | Add `status` column to `comments` table; update `comment_row_to_dict()` |
| `backend/routers/comments_api.py` | Insert generated comments with `status='generated'`; add approve/publish endpoints; update `CommentOut` |
| `backend/main.py` | Filter public comment display to `status='published'`; update admin comments route to pass status counts |
| `frontend/templates/admin_comments.html` | Add status badges, approve/publish action buttons, summary strip |
| `backend/tests/test_comments.py` | Add tests for status column, approve/publish endpoints, public visibility filtering |

## Files to Create

None. All changes fit within existing files.

---

## Database Migration (`backend/db.py`)

Add `status` column to `comments` with default `'published'` so all existing comments remain visible:

```python
comment_cols = {row[1] for row in conn.execute("PRAGMA table_info(comments)")}
if "status" not in comment_cols:
    conn.execute("ALTER TABLE comments ADD COLUMN status TEXT NOT NULL DEFAULT 'published'")
```

Update `comment_row_to_dict()` to include `status` in the returned dict.

**Why `'published'` as default:** Existing AI comments are already live on the site. Retroactively hiding them would break the public view. New AI comments will explicitly get `status='generated'`.

---

## Schema Changes (`backend/routers/comments_api.py`)

Add `status: str = "published"` to `CommentOut`.

**Human comments** — `create_comment()` inserts with `status='published'` explicitly. Always immediately visible.

**AI comments** — `CommentGenerator.generate_and_insert()` inserts with `status='generated'`. Not visible until published by admin.

---

## New API Endpoints (`backend/routers/comments_api.py`)

| Method | Path | Description |
|--------|------|-------------|
| `PATCH` | `/api/comments/{id}/approve` | Sets `status='approved'`. Returns 409 if not in `generated` state. |
| `PATCH` | `/api/comments/{id}/publish` | Sets `status='published'`. Returns 409 if not in `approved` state. |

State machine — strict sequential:
```
generated → approved → published
```
Skipping states is not allowed. Both endpoints return 404 if comment not found.

---

## Public Visibility Filter (`backend/main.py`)

In `GET /blog/{slug}` and `POST /blog/{slug}/comments`, change the comment query:

```sql
-- Before
SELECT * FROM comments WHERE post_slug = ? ORDER BY created_at ASC

-- After
SELECT * FROM comments WHERE post_slug = ? AND (status = 'published' OR is_generated = 0) ORDER BY created_at ASC
```

This ensures real (human) comments always show regardless of status, and only AI comments that have been explicitly published are visible.

---

## Admin UI (`frontend/templates/admin_comments.html`)

**Status badges** per comment row:
- `generated` → violet badge "Generated"
- `approved` → amber badge "Approved"
- `published` → green badge "Published"

**Action buttons** per comment (HTMX, swap the comment row `outerHTML`):
- `generated` → "Approve" button: `hx-patch="/api/comments/{id}/approve"`
- `approved` → "Publish" button: `hx-patch="/api/comments/{id}/publish"`
- `published` → no action button (already live)

**Summary strip** at top of page:
- Count of comments in `generated` state (awaiting review)
- Count of comments in `approved` state (ready to publish)
- Count of `published` AI comments

Delete button remains available for all statuses.

**Admin hub** (`admin_hub.html`): show a pending-review count badge (sum of `generated` + `approved`) on the Comments card to draw attention.

---

## The `ai_comments` Toggle on Posts

The existing `ai_comments` toggle on `/admin/posts` remains as-is. It controls whether the scheduler **generates** new AI comments for a post. It does NOT gate the approve/publish workflow — that is independent.

- Toggle OFF: scheduler skips this post; already-generated comments can still be approved/published.
- Toggle ON: scheduler will generate new comments for this post on the next cycle.

---

## Risks & Trade-offs

1. **Migration safety:** `DEFAULT 'published'` keeps all existing comments live. Existing AI comments cannot be retroactively put back through the workflow — this is acceptable.

2. **Two-step vs one-step:** Generated → Approved → Published allows the admin to batch-review before releasing. A simpler single-step (Generated → Published) would also work but gives less control. Two-step matches the draft workflow pattern already in the codebase.

3. **Real comments bypass the workflow:** Human-submitted comments get `status='published'` immediately and are always visible. The approval workflow is only for AI-generated content.

4. **`list_comments` API returns all statuses:** The REST `GET /api/comments?post_slug=X` returns all comments (including non-published) so admin tooling can see everything. Only the public HTML route filters to `status='published'`.

---

## Tests (`backend/tests/test_comments.py`)

```
# Status column
test_generated_comment_has_status_generated
test_real_comment_has_status_published
test_comment_out_includes_status_field

# Approve endpoint
test_approve_comment_returns_200
test_approve_comment_sets_status_approved
test_approve_non_generated_returns_409
test_approve_nonexistent_returns_404

# Publish endpoint
test_publish_comment_returns_200
test_publish_comment_sets_status_published
test_publish_non_approved_returns_409
test_publish_nonexistent_returns_404

# Public visibility
test_public_post_hides_generated_comments
test_public_post_hides_approved_comments
test_public_post_shows_published_ai_comments
test_public_post_always_shows_real_comments

# Admin page
test_admin_comments_shows_status_badges
test_admin_comments_shows_approve_button_for_generated
test_admin_comments_shows_publish_button_for_approved
test_admin_comments_shows_status_counts
```

---

## Critical Files

- `backend/db.py` — migration
- `backend/routers/comments_api.py` — status field, approve/publish endpoints
- `backend/main.py` — public visibility filter, admin route context
- `frontend/templates/admin_comments.html` — status badges + action buttons
- `backend/tests/test_comments.py` — new test cases
