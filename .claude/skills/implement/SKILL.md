---
name: implement
description: Implement a feature from its design spec in docs/specs/<feature>.md. Decomposes the spec into independent tasks and runs parallel subagents for fast delivery. Always run /design first.
argument-hint: [feature-name]
---

# Implement Skill

You are the implementation coordinator. Your job is to implement a feature that has already been designed.

## Steps

1. **Parse the feature name** from `$ARGUMENTS`.

2. **Read the spec** at `docs/specs/$ARGUMENTS.md`. If it does not exist, tell the user to run `/design $ARGUMENTS` first.

3. **Validate the spec** — check that it has:
   - Files to Modify / Create
   - Implementation Plan
   - Tests Needed

4. **Decompose into independent tasks** — identify which parts of the implementation can be done in parallel (e.g., different modules, tests vs. implementation).

5. **Launch parallel general-purpose subagents** for independent tasks:
   - Each agent gets: the spec content, the specific task it owns, and instructions to write code and tests
   - Agents must NOT overlap on the same files
   - Typically: 2-4 agents depending on scope

6. **Wait for all agents** to complete.

7. **Integrate results** — review what was written, resolve any conflicts, and ensure everything connects.

8. **Run a final check**:
   - Are all files from the spec created/modified?
   - Do tests exist for the new code?
   - Do all tests pass? (`cd backend && uv run pytest`)
   - Does the code follow `.claude/rules/code-style.md`?

9. **Report to the user**: what was implemented, what files changed, next step is `/simplify`.

## Rules

- Never implement something not in the spec — stay in scope
- Each subagent must get complete context (spec + task + relevant existing code)
- Do not skip tests — they are part of implementation
- If a spec is ambiguous, resolve ambiguity before spawning agents
