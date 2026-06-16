# Admin Authentication

All routes under `/admin/*` are protected by a single-password session. There is no
user database — one password, one admin.

## How it works

- **SessionMiddleware** (Starlette, backed by `itsdangerous`) signs a cookie named
  `zdenovo_session`. The cookie is tamper-proof but not encrypted; it stores only a
  boolean flag (`{"admin": true}`).
- `require_admin` is a FastAPI `Depends` attached to every `/admin/*` route. If the
  session flag is missing, the request is redirected to `/admin/login?next=<original path>`.
- `POST /admin/login` compares the submitted password against `ADMIN_PASSWORD` using
  `secrets.compare_digest` (constant-time, safe against timing attacks). On success it
  sets the session flag and redirects to `next`.
- `POST /admin/logout` clears the session and redirects to `/admin/login`.
- The public blog (`/`, `/blog/*`) and comment submission (`POST /blog/{slug}/comments`)
  are NOT protected.

## Setup

### 1. Set environment variables

Add to your `.env` (local) or server environment (prod):

```bash
ADMIN_PASSWORD=your-strong-password-here
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

`SECRET_KEY` signs the session cookie. If it changes, all existing sessions are
invalidated — every browser will be asked to log in again.

### 2. Development defaults

If `ADMIN_PASSWORD` is not set or empty, login always fails. The dev `.env` sets
`ADMIN_PASSWORD=admin` — change it before deploying.

`SECRET_KEY` falls back to a hardcoded insecure string when missing. The startup log
will not warn you — just always set it in production.

### 3. Production checklist

- [ ] `ADMIN_PASSWORD` set to a strong password in the server's `.env`
- [ ] `SECRET_KEY` set to a fresh random hex string (see command above)
- [ ] HTTPS enabled (the `SessionMiddleware` is configured with `https_only=False` now;
  change to `True` after SSL is in place so the cookie is `Secure`)
- [ ] `ADMIN_PASSWORD` and `SECRET_KEY` never committed to git (both are in `.env`,
  which is gitignored)

## Enabling `Secure` cookie in production

Once SSL is active, edit `main.py`:

```python
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "..."),
    session_cookie="zdenovo_session",
    max_age=60 * 60 * 24 * 7,
    https_only=True,   # ← change this
)
```

## Protected routes

| Route | Protected |
|-------|-----------|
| `GET /admin/login` | No (login page itself) |
| `POST /admin/login` | No |
| `POST /admin/logout` | No (clearing a session is always safe) |
| `GET /admin` | Yes |
| `GET /admin/posts` | Yes |
| `GET /admin/drafts` | Yes |
| `GET /admin/drafts/{id}` | Yes |
| `GET /admin/comments` | Yes |
| `POST /admin/drafts/{id}` (edit form) | Yes |

> **Note:** The JSON API routes under `/api/*` (delete post, delete comment, etc.) are
> currently not auth-protected. They are used by HTMX from within the admin pages. If
> the admin URL is not publicly known, this is acceptable. To harden further, apply the
> same `require_admin` dependency to those routers.

## Session lifetime

Sessions expire after **7 days** of inactivity (configured via `max_age`). To force
immediate logout of all sessions, rotate `SECRET_KEY`.
