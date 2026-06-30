---
name: security-review
description: Run a security review of changed files before merging to main. Checks auth guards, XSS, SQL injection, CSRF, open redirects, and hardcoded secrets.
argument-hint: [optional base branch, default: main]
---

# Security Review

Review the changes on the current branch against `main` (or `$ARGUMENTS` if a base
branch/ref is given) for security issues before merging. This is Layer 3 of the security
gate — a manual, AI-powered review that runs before a PR/merge, complementing automated
tests and pre-push hooks.

## Step 1 — Get the diff

Determine the base ref: use `$ARGUMENTS` if provided, otherwise `main`.

```bash
git branch --show-current
git diff <base>...HEAD --name-only          # list changed files
git diff <base>...HEAD -- '*.py' '*.html' '*.js'   # full diff of code files
```

If currently on `main` (or `<base>` IS the current branch, so there's nothing to diff
against it), fall back to reviewing the last commit instead:

```bash
git diff HEAD~1..HEAD --name-only
git diff HEAD~1..HEAD -- '*.py' '*.html' '*.js'
```

If there are no changed files, report **PASS** immediately with "no changes to review"
and stop.

## Step 2 — Read changed files in full

For each changed Python, HTML template, and JS file, use the Read tool to read the
**entire file**, not just the diff hunk. Reviewing only the diff misses context — e.g. a
route's auth decorator three lines above the changed hunk, or a Jinja `{% block %}` that
wraps the changed line. Reading the full file is required, not optional.

## Step 3 — Run the checklist

For every changed file, check against this table. Use `grep -n` for fast scans, then
confirm with the full file read from Step 2.

| # | Check | How to verify |
|---|-------|---------------|
| 1 | All `POST`/`PATCH`/`DELETE`/`PUT` routes have `require_admin` (or are intentionally public, e.g. comments/contact forms) | Scan route decorators in `routers/*.py` and `main.py` for the dependency; check the function body for an explicit admin check |
| 2 | No `\| safe` filter in Jinja2 templates (XSS) | `grep -rn '\| safe' frontend/templates/` |
| 3 | No f-string / `.format()` / `%`-built SQL queries (injection) | Look for `f"...SELECT...{var}` or string concatenation feeding `cursor.execute(...)`; all queries must use `?` placeholders |
| 4 | No hardcoded secrets or tokens | Look for API keys, passwords, or tokens assigned to variables or string literals instead of `os.environ` / `.env` |
| 5 | CSRF: state-changing HTML `<form>`s have a CSRF token | Check POST forms in `frontend/templates/` for `{{ csrf_token }}` or equivalent hidden field |
| 6 | Open redirect: `next=` or redirect query params use an allowlist, not arbitrary URLs | Check redirect logic in `main.py` (auth) for unchecked `RedirectResponse(request.query_params...)` |
| 7 | Rate limiting on public POST endpoints | Check for slowapi decorators (`@limiter.limit(...)`) on public routes, e.g. comments, generation triggers |
| 8 | New dependencies: any new packages added to `pyproject.toml` that look suspicious (typosquats, unmaintained, unnecessary) | `git diff <base>...HEAD -- pyproject.toml` |
| 9 | No `assert` used for security/auth checks (stripped under `python -O`) | `grep -n 'assert ' <changed files>` — flag any guarding auth/permissions |
| 10 | No `shell=True` in `subprocess` calls | `grep -n 'shell=True' <changed files>` |

Treat checks 1, 3, 4 as the highest severity (auth bypass, SQLi, leaked secrets) — any
hit there is an automatic BLOCK candidate. Checks 5–10 are typically WARN unless clearly
exploitable (e.g. an unauthenticated open redirect used in the login flow).

## Step 4 — Verdict

Classify the overall result:

- **PASS** — all checks clean, safe to merge.
- **WARN** — minor issues found (e.g. missing rate limit on a low-risk endpoint, a
  redundant `assert` in a non-security path) — document them; fixing is optional before
  merge but should be tracked.
- **BLOCK** — a critical issue found (unprotected admin route, SQL injection, XSS via
  `| safe`, hardcoded secret, CSRF-less destructive form, open redirect in auth) — must
  be fixed before merging.

## Step 5 — Report

Print a structured report in this format:

```
=== Security Review ===
Branch: <branch> → <base>
Files changed: N

Checklist:
  [✓/✗] 1. Auth guards on all routes
  [✓/✗] 2. No | safe in templates
  [✓/✗] 3. No f-string SQL
  [✓/✗] 4. No hardcoded secrets
  [✓/✗] 5. CSRF tokens on forms
  [✓/✗] 6. Open redirect allowlist
  [✓/✗] 7. Rate limiting on public POST routes
  [✓/✗] 8. New dependencies reviewed
  [✓/✗] 9. No assert for security checks
  [✓/✗] 10. No shell=True

Verdict: PASS | WARN | BLOCK

Issues to fix before merging:
  1. [file:line] description
  2. [file:line] description

Notes:
  - <anything observed worth flagging that isn't a hard checklist failure>
```

Only list checklist items that are relevant to the changed files (e.g. skip the CSRF
check entirely if no templates changed — mark it `n/a` rather than `✓`). Be specific:
every finding must cite a file path and line number.
