# Spec: Comments

Readers can leave a comment (username + body) on any `/blog/{slug}` post. Comments display in chronological order beneath the post content. Admin can delete any comment at `/admin/comments`. No authentication — just a username field.

---

## Files to Modify

| File | Reason |
|------|--------|
| `backend/db.py` | Add `comments` table in `init_db()`; add `comment_row_to_dict()` helper |
| `backend/main.py` | Wire `comments_router`; add `POST /blog/{slug}/comments` HTMX handler; add `GET /admin/comments` page |
| `frontend/templates/post.html` | Add `#comments-section` below article |
| `backend/routers/posts_api.py` | Delete orphaned comments when a post is deleted |

## Files to Create

| File | Reason |
|------|--------|
| `backend/routers/comments_api.py` | REST API: GET list, POST create, DELETE |
| `frontend/templates/comments_section.html` | HTMX partial: comment list + submission form |
| `frontend/templates/admin_comments.html` | Admin page: all comments with delete buttons |
| `backend/tests/test_comments.py` | Full test suite |

---

## Database

Table: `comments`

```sql
CREATE TABLE IF NOT EXISTS comments (
    id         TEXT PRIMARY KEY,
    post_slug  TEXT NOT NULL,
    author     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
)
```

`comment_row_to_dict(row)` — parses `created_at` to `datetime`, returns dict.

---

## REST API (`routers/comments_api.py`)

Router prefix: `/api/comments`, tag: `"comments"`.

### Schemas

```python
class CommentIn(BaseModel):
    post_slug: str
    author: str = Field(..., min_length=1, max_length=80)
    body: str = Field(..., min_length=1, max_length=2000)

class CommentOut(BaseModel):
    id: str
    post_slug: str
    author: str
    body: str
    created_at: datetime
```

### Endpoints

| Method | Path | Behaviour |
|--------|------|-----------|
| `GET` | `/api/comments?post_slug={slug}` | All comments for a post, oldest first. Returns `[]` if none. |
| `POST` | `/api/comments` | Validate post exists (404 if not), insert, return `CommentOut` 201. |
| `DELETE` | `/api/comments/{id}` | Delete comment; 204 on success, 404 if not found. |

---

## HTML endpoints (`main.py`)

### `POST /blog/{slug}/comments`

HTMX form handler — accepts `Form(author, body)`, inserts comment, re-fetches comments for slug, returns `comments_section.html` partial as response (HTMX swaps `#comments-section` innerHTML).

Validation: post must exist (return 404 if not). Author and body must be non-empty.

### `GET /admin/comments`

Fetches all comments ordered by `created_at DESC`, renders `admin_comments.html`.

---

## Templates

### `comments_section.html` (Jinja2 partial, not full page)

Context variables: `comments` (list of dicts), `slug` (str).

Content:
1. Heading: "Comments (N)"
2. List of comments: author name (bold), body, formatted date. Empty state: "No comments yet. Be the first."
3. Submission form:
   - `hx-post="/blog/{{ slug }}/comments"`
   - `hx-target="#comments-section"`
   - `hx-swap="innerHTML"`
   - Fields: `author` text input (placeholder "Your name", max 80), `body` textarea (placeholder "Leave a comment...", max 2000)
   - Submit button

### `post.html`

Add below `</article>`:

```html
<section id="comments-section" class="mt-16 pt-8 border-t border-zinc-800/60">
  {% include "comments_section.html" %}
</section>
```

Pass `comments` and `slug` from the route handler.

### `admin_comments.html`

Extends `base.html`. Lists all comments with: author, post slug (link to `/blog/{slug}`), body (truncated to 120 chars), date, delete button using:
- `hx-delete="/api/comments/{comment.id}"`
- `hx-target="#comment-{comment.id}"`
- `hx-swap="outerHTML"`
- `hx-confirm="Delete this comment?"`

---

## Cascade on post delete

In `routers/posts_api.py`, `delete_post` handler: before deleting the post, also run:
```sql
DELETE FROM comments WHERE post_slug = ?
```

---

## Tests Needed (`backend/tests/test_comments.py`)

```
test_list_comments_returns_200
test_list_comments_empty_for_unknown_slug
test_list_comments_returns_existing_comments_oldest_first
test_create_comment_returns_201
test_create_comment_post_not_found_returns_404
test_create_comment_empty_author_returns_422
test_create_comment_empty_body_returns_422
test_create_comment_author_too_long_returns_422
test_create_comment_appears_in_list
test_delete_comment_returns_204
test_delete_comment_removes_it
test_delete_comment_not_found_returns_404
test_delete_post_also_deletes_comments
test_post_detail_includes_comments_section
test_admin_comments_returns_200
test_admin_comments_lists_all_comments
test_comment_form_submit_returns_partial
```
