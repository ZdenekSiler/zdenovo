# Git Workflow Rules

## Branch Naming

```
feature/<short-description>     # New features
fix/<short-description>         # Bug fixes
chore/<short-description>       # Maintenance, refactoring
docs/<short-description>        # Documentation only
```

Examples:
- `feature/user-auth`
- `fix/cart-total-overflow`
- `docs/update-readme`

## Commit Messages

Use Conventional Commits format:

```
<type>(<scope>): <short summary>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`

Examples:
```
feat(auth): add JWT refresh token support
fix(cart): prevent negative total on discount overflow
docs(readme): add Claude Code integration section
```

Rules:
- Subject line max 72 characters
- Use imperative mood ("add" not "added")
- Reference issues in footer: `Fixes #123`

## Pull Requests

- Title follows commit message format
- Include a description of what changed and why
- Link to the relevant spec in `docs/specs/` if applicable
- All tests must pass before merging (`cd backend && uv run pytest`)
- This is a solo-maintained project — self-review the diff before merging instead of waiting on a reviewer

## Protected Branches

- `main` — production. The server runs `git pull` on this branch via `make deploy`, so only merge tested, working code.

## Secrets

- Never commit `.env` (gitignored) — it holds `ANTHROPIC_API_KEY`, `CERTBOT_EMAIL`,
  `SERVER_HOST`, and other production credentials.
- New environment variables go in `.env.example` with a placeholder value, never a
  real one.
- Never display, log, or echo the contents of `.env` — including in command output
  or commit messages.
