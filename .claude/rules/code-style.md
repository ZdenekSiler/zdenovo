# Code Style Rules

## Python (backend/)

- 4-space indentation, PEP 8
- Double quotes for strings
- Type hints on all function signatures, including return types
- `snake_case` for functions, variables, and modules
- `PascalCase` for Pydantic models and classes (`PostIn`, `PostOut`, `DraftOut`)
- Private helpers prefixed with `_` (`_slugify`, `_load_seed`, `_call_claude`)
- Section dividers as comments for long files:
  ```python
  # ─── Schemas ──────────────────────────────────────────────────────────────────
  ```

## FastAPI Conventions

- One `APIRouter` per domain in `routers/`, mounted in `main.py` via `app.include_router(...)`
- Request/response shapes are Pydantic models (`*In` for input, `*Out` for output)
- Raise `HTTPException` with explicit `status_code` and `detail` for error paths
- Database access goes through `db.get_conn()` / `db.row_to_dict()` — no ORM

## Frontend (frontend/static/js, frontend/templates)

- 2-space indentation, semicolons, `camelCase`
- Wrap page scripts in an IIFE: `(function () { ... })();`
- No build step — Tailwind via CDN, vanilla JS, Jinja2 templates
- Use HTMX attributes (`hx-get`, `hx-target`, `hx-swap`, `hx-push-url`) for partial-page navigation instead of custom fetch/XHR code

## Comments

- Write comments for non-obvious logic only (e.g. a migration step, a workaround)
- No commented-out code in commits
- Docstrings only where behavior isn't obvious from the signature (e.g. scheduler entry points)
