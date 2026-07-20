# Debugging Rules

When investigating **any** issue (local or prod), keep a complete, ordered record of the
commands run so it can be reviewed and reproduced. The point is that after a debugging
session, the user can see *exactly* what was executed — no hidden steps.

**This log is a debugging *and learning* aid for the user.** Optimize it for understanding,
not just reproducibility:

- Explain **why** each command was run and **what its result told us** — the reasoning, not
  just the syntax.
- Briefly gloss non-obvious flags, pipelines, or tools (e.g. `-w "%{http_code}"`,
  `exec -T`, `grep -nE`) so the user learns the technique, not just the outcome.
- Show how one command's result led to the next — make the investigation path legible.
- When something failed, explain the failure and what it ruled in/out, so the dead ends
  teach too.

## Keep a command log

- Record **every** command run during the investigation, in order — not just the ones that
  "worked". Failed attempts and dead ends are part of the story.
- For each command capture: the **exact command**, its **purpose** (one line), and the
  **outcome** (exit code / key output, or the error).
- Mark whether a command was **read-only** (inspecting) or **mutating** (changed state).

## Surface it to the user

- At the end of a debugging session — or whenever the user asks — print the full command
  list, in order, copy-pasteable, with outcomes. Don't summarize it away.
- The `/recap debug` skill produces exactly this structured summary — prefer it for
  wrapping up a debug session rather than hand-rolling one.
- If the user asks "what did you run?" mid-session, answer with the actual commands, not a
  paraphrase.

## Flag anything that touched prod

- Clearly label commands that ran against production — e.g. `ssh zdenovo ...`,
  `docker compose -f docker-compose.prod.yml exec ...`, or any `curl` to the live domain.
- Note mutating prod actions explicitly so they're easy to spot and, if needed, reverse.

## Never leak secrets in the log

- Follow @.claude/rules/git.md — never echo `.env` or `secrets/` contents. When a command
  needs a secret, read it into a variable without printing it, and show the command with
  the secret redacted (e.g. `--password <redacted>`) in the recap.
