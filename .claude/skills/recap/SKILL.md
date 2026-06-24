---
name: recap
description: Print a structured summary of what happened during a deploy or debug session — commands run, outcomes, and what to watch.
argument-hint: [deploy|debug]
---

# Session Recap

Print a concise, structured recap of the current session. Use this at the end of a deploy or after debugging an issue.

## When to use

- After a `/deploy` completes (success or failure)
- After diagnosing and fixing a production issue
- When the user asks "what just happened?" or wants a log of actions taken

## Output format

Print the recap directly as formatted text. Do NOT create a file.

### For a deploy session (`/recap deploy`):

```
## Deploy Recap — <date>

**Commit:** `<hash>` — <commit message>
**Branch:** main

### Steps performed
1. `<command>` — <what it did and result>
2. `<command>` — <what it did and result>
...

### Test results
- Unit: <count> passed / <count> failed
- Playwright: <count> passed / <count> failed

### Verification
- Status: <HTTP status>
- Posts: <count>
- URL: https://zdenovo.com

### What changed
- <bullet summary of files/features changed>
```

### For a debug session (`/recap debug`):

```
## Debug Recap — <date>

**Issue:** <one-line description of what was wrong>
**Root cause:** <what caused it>
**Resolution:** <what fixed it>

### Investigation steps
1. `<command>` — <what we learned>
2. `<command>` — <what we learned>
...

### Fix applied
- <file>:<line> — <what changed>

### Verification
- <how we confirmed the fix works>

### Watch for
- <anything to monitor after the fix>
```

## Rules

- Reconstruct the recap from the current conversation context — what commands were run, what output they produced, what decisions were made.
- Include the actual commands with backtick formatting so the user can re-run them.
- Keep it factual — no opinions, no suggestions for future work.
- If tests failed, note which ones and whether they were pre-existing or new.
- For deploy recaps, always include the commit hash and the verification result.
- For debug recaps, always include the root cause and what to watch for.
