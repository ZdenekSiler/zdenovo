# Development Workflows

## Design-Then-Implement Workflow

All non-trivial features follow this workflow:

```
1. /design <feature>
       |
       v
   Explore agents research codebase (parallel)
       |
       v
   Plan agent writes spec → docs/specs/<feature>.md
       |
       v
2. Review the spec in docs/specs/<feature>.md
       |
       v
3. /implement <feature>
       |
       v
   Read spec, decompose into tasks
       |
       v
   Parallel subagents implement each task
       |
       v
   Main agent integrates results
       |
       v
4. /simplify
       |
       v
   Code quality review and cleanup
       |
       v
5. uv run pytest   ← tests must pass before committing
       |
       v
6. git commit
```

## Quick Fix Workflow

For small, isolated fixes (typos, config changes, obvious bugs):

1. Make the change directly (no design needed)
2. Run `/simplify` to verify no over-engineering
3. `cd backend && uv run pytest`
4. Commit only if green

## Adding a Feature End-to-End

```bash
# 1. Create a branch
git checkout -b feature/my-feature

# 2. Design
/design my-feature

# 3. Review the spec
cat docs/specs/my-feature.md

# 4. Implement
/implement my-feature

# 5. Clean up
/simplify

# 6. Test — must be green before committing
cd backend
uv run pytest
uv run pytest --cov --cov-report=term-missing

# 7. Commit
git add -A
git commit -m "feat: add my-feature"
git push origin feature/my-feature
```

For test file layout and conventions, see @.claude/rules/testing.md. For the skill
reference table (trigger, output), see the "Custom Skills" section of `CLAUDE.md`.
