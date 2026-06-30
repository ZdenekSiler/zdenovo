# zdenovo — Claude Code Project

## Project Overview

This is a Claude Code project template demonstrating best practices for AI-assisted development. It uses a design-then-implement workflow powered by custom skills and parallel subagents.

## Architecture

See @docs/architecture.md for module layout and key decisions.

**Data model:** SQLite with tables `posts` (slug PK), `drafts` (UUID PK), `comments` (UUID PK).
Tags stored as JSON arrays. Schema and migrations in `backend/db.py` → `init_db()`.

**AI prompts:** Generation rules live in `backend/data/prompts/` (Markdown + JSON tool schemas),
not in Python code. Edit the template files to change generation behavior.

## Workflows

See @docs/workflows.md for the design-then-implement workflow.

## Build & Test

```bash
# Install dependencies (from backend/)
uv sync

# Run the dev server
uv run uvicorn main:app --reload

# Run tests
uv run pytest

# Add a dependency
uv add <package>
```

## Development

```bash
make dev          # Start dev server → http://localhost:8080
make test         # Run test suite with coverage
make dev-logs     # Tail logs
make dev-down     # Stop
```

## Production (Hetzner / any Ubuntu VPS)

```bash
# One-time: copy and fill in values
cp .env.example .env

# First deploy to a fresh server (from local machine)
make deploy-first  # Installs Docker, clones repo, gets SSL cert, starts app

# Push code updates
make deploy        # git pull + restart on server

# Health check
make check         # Verifies HTTPS, redirect, and API
```

See `docs/deployment.md` for full deployment guide.

## Code Conventions

- @.claude/rules/code-style.md — formatting and naming
- @.claude/rules/architecture.md — where code goes, module/import rules, API conventions
- @.claude/rules/testing.md — test structure and coverage
- @.claude/rules/git.md — branches, commits, PRs

## Custom Skills

| Skill | When to use |
|-------|-------------|
| `/design <feature>` | Before writing any code — produces a spec in `docs/specs/` |
| `/implement <feature>` | After `/design` — implements the spec using parallel subagents |
| `/simplify` | After implementing — reviews code quality and removes redundancy |
| `/recap deploy` or `/recap debug` | End of a deploy or debug session — prints structured summary of commands and outcomes |
| `/security-review` | Before merging — AI-powered review of changed files for auth gaps, XSS, SQL injection, CSRF, secrets |

## Key Principles

- Always run `/design` before `/implement` for any non-trivial feature
- Keep CLAUDE.md under 200 lines; put detail in `.claude/rules/` and `docs/`
- Use parallel subagents to decompose independent tasks for speed
- Commit only working, tested code
