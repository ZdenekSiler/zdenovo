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
- All tests must pass before merging
- At least one review required

## Protected Branches

- `main` — production, protected, requires PR
- `develop` — integration branch, requires PR
