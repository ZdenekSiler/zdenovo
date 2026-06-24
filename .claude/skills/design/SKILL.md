---
name: design
description: Design a feature or component before writing code. Launches parallel Explore agents to research the codebase, then produces a spec in docs/specs/<feature>.md. Use this before /implement for any non-trivial change.
context: fork
agent: Plan
argument-hint: [feature-name]
---

# Design Skill

You are the design agent. Your job is to produce a detailed feature spec **before any code is written**.

## Steps

1. **Parse the feature name** from `$ARGUMENTS`. If none provided, ask the user what to design.

2. **Launch 2-3 parallel Explore agents** to research relevant parts of the codebase:
   - Agent 1: Explore existing related code, interfaces, and types
   - Agent 2: Explore tests and how similar features are tested
   - Agent 3 (if needed): Explore docs and architecture for context

3. **Synthesize findings** from all Explore agents.

4. **Write the spec** to `docs/specs/$ARGUMENTS.md` with these sections:
   - **Overview** — what the feature does and why
   - **Current State** (if modifying existing flows) — what exists now, how it behaves
   - **Files to Modify** — list with brief reason for each
   - **Files to Create** — list with brief reason for each
   - **Implementation Plan** — step-by-step breakdown
   - **Tests Needed** — what tests to write
   - **Risks & Trade-offs** — anything to watch out for

5. **Summarize** to the user: spec is ready at `docs/specs/$ARGUMENTS.md`, next step is `/implement $ARGUMENTS`.

## Rules

- Do NOT write any code — only write the spec file
- Do NOT make assumptions about missing context — use Explore agents to find it
- Keep the spec under 150 lines. If longer, split into phases.
- Keep the spec concise but complete enough to implement without further research
- Create `docs/specs/` directory if it doesn't exist
