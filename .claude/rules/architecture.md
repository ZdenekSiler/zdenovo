# Architecture Rules

Where code goes and how modules depend on each other. For the descriptive reference
(endpoints, schemas, pipeline, key decisions), see @docs/architecture.md.

## Module Layout — Where New Code Goes

| Code | Goes in |
|------|---------|
| HTML page route | `main.py` (or a new router included from `main.py` if the page grows a family of routes) |
| DB schema, connection, seed/migration logic | `db.py` — no business logic here |
| Read-only query helper for an HTML page | `data/<name>.py` |
| Static/config data (topics, briefs) | `data/<name>.json`, loaded by the module that uses it |
| New REST resource | New `routers/<name>_api.py` with its own `APIRouter`, mounted in `main.py` via `app.include_router(...)` |
| Jinja2 template | `frontend/templates/` |
| CSS / JS | `frontend/static/css/`, `frontend/static/js/` |
| Test for module `X` | `backend/tests/test_X.py` (mirrors the module under test) |

## Import & Dependency Rules

- Group imports stdlib → third-party → internal, blank line between groups; no unused imports.
- `db` is the foundation — every router and `data/` module may import it; it imports nothing internal.
- `data.posts`, `data.projects` are read-only helpers for HTML routes — they don't import from `routers/`.
- Router dependency direction is **one-way only**:
  `routers/posts_api.py` → `routers/generate_api.py` → `routers/drafts_api.py`
  - `generate_api` may import from `posts_api` (`PostOut`, `_slugify`)
  - `drafts_api` may import from `generate_api` (`PostBrief`, `_build_brief_message`, `_call_claude`)
  - Never the reverse — this avoids circular imports. If a new module needs something from
    a module "below" it in this chain, that's a sign the shared code belongs in `db.py` or
    a new shared module instead.

## API Conventions

- One `APIRouter` per domain in `routers/`, mounted once in `main.py`.
- Request/response bodies are Pydantic models: `*In` for input, `*Out` for output (see
  @.claude/rules/code-style.md for naming).
- Error paths raise `HTTPException(status_code=..., detail=...)` — never return error
  shapes as 200 responses.
- All DB access goes through `db.get_conn()` / `db.row_to_dict()` — no ORM.
- New endpoints get a row in the API table in @docs/architecture.md.

## Two Communication Surfaces — Keep Them Separate

- **Server-rendered HTML** (`/`, `/projects`, `/blog`, `/blog/{slug}`, `/admin/drafts*`) —
  Jinja2 `TemplateResponse`s defined in `main.py`. Navigation uses HTMX attributes
  (`hx-get`, `hx-target`, `hx-push-url`, `hx-swap`) for partial swaps — never hand-roll
  fetch/XHR for nav.
- **JSON REST API** (`/api/*`) — independent of the HTML pages, lives in `routers/`,
  self-documented via Swagger UI at `/docs`.

Don't blend the two: an HTML route returns a template, an API route returns a Pydantic
model or raises `HTTPException`.

## Checklist: Adding a New Module or Endpoint

1. Pick the right location using the table above.
2. If it's a new REST resource, create `routers/<name>_api.py` with its own `APIRouter`
   and mount it in `main.py`.
3. Define `*In`/`*Out` Pydantic models for the request/response shape.
4. Add any new DB tables/columns to `db.py` (`init_db()` must handle migrating existing
   databases, e.g. adding a column with `ALTER TABLE`).
5. Add templates under `frontend/templates/` for new HTML pages.
6. Write tests in the matching `backend/tests/test_<module>.py` (see @.claude/rules/testing.md).
7. Document new endpoints in the API Endpoints tables in @docs/architecture.md.
