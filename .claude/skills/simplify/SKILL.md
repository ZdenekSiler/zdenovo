---
name: simplify
description: Review recently changed code for quality, reuse, and efficiency. Find and fix over-engineering, duplication, and unnecessary complexity. Run this after /implement.
---

# Simplify Skill

Review the code changes made in this session and improve their quality.

## Steps

1. **Identify changed files** — look at files modified or created in this session.

2. **For each changed file, check**:
   - Is there duplicated logic that could be extracted into a shared utility?
   - Are there abstractions that are only used once (remove them)?
   - Are there helper functions, types, or variables that are never used?
   - Is error handling added for scenarios that cannot realistically happen?
   - Are there backwards-compatibility shims for code that hasn't been published?
   - Are comments explaining what the code does rather than why?
   - Is the naming clear and consistent with `.claude/rules/code-style.md`?

3. **Fix issues found** — make targeted edits. Do not refactor code that wasn't changed.

4. **Verify** — ensure the code still works after simplification (check for broken references).

5. **Summarize** what was simplified and why.

## Rules

- Only touch files that were changed in this session
- Do not add features or expand scope
- Do not add comments, docstrings, or type annotations to code you didn't change
- Do not introduce backwards-compatibility hacks
- The goal is the minimum code needed — three similar lines is better than a premature abstraction
