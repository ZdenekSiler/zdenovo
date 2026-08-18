---
name: generate-post
description: Generate a blog post draft via the API. Provide a topic description or brief ID. The post goes through Claude generation + AI slop review, then lands in drafts for admin approval.
argument-hint: <topic description or brief ID>
---

# Generate Blog Post

Generate a new blog post draft and submit it for review.

## How it works

The blog generation pipeline lives in the FastAPI backend. It:
1. Sends the topic to Claude with rules from `backend/data/prompts/blog_system.md`
2. Claude outputs structured content via the `write_post` tool (`backend/data/prompts/blog_tool.json`)
3. A second Claude call reviews the post for AI slop using `backend/data/prompts/blog_review.md`
4. If the review fails, it retries up to 3 times, keeping the best attempt
5. The result is saved as a draft with status `pending`

## Steps

1. **Parse the argument.** `$ARGUMENTS` is either:
   - A free-text topic description (e.g., "why SQLite is underrated for small projects")
   - A brief ID from `backend/data/post_briefs.json` (e.g., "ollama-local-llm")

2. **Check available briefs** if the argument looks like an ID:
   ```bash
   curl -s http://localhost:8080/api/posts/briefs | python3 -m json.tool
   ```

3. **Generate the draft.** Call the appropriate endpoint:

   For a free-text topic:
   ```bash
   curl -s -X POST http://localhost:8080/api/posts/generate \
     -H "Content-Type: application/json" \
     -d '{"description": "<topic>", "tags": []}'
   ```

   For a brief ID:
   ```bash
   curl -s -X POST http://localhost:8080/api/posts/generate/<brief_id>
   ```

4. **Report the result.** Show:
   - Draft title and ID
   - Quality score and verdict (pass/fail)
   - Issues found by the reviewer
   - Strengths noted
   - Link to preview: `http://localhost:8080/admin/drafts/<id>`

5. **Verify the sources before approving.** Generated source URLs are the least reliable part
   of the output — the model can reconstruct a plausible-looking URL that 404s. Check them:
   ```bash
   curl -s http://localhost:8080/api/drafts/<id> | python3 -c "
   import sys, json, urllib.request
   UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
   for s in json.load(sys.stdin).get('sources') or []:
       try:
           req = urllib.request.Request(s['url'], headers={'User-Agent': UA})
           print(urllib.request.urlopen(req, timeout=12).status, s['url'])
       except Exception as e:
           print('FAIL', getattr(e, 'code', type(e).__name__), s['url'])"
   ```
   **Read the failures before acting on them** — 403 and 429 mean the host blocks bots
   (Medium and DataCamp always do), not that the page is gone. Only 404/410 and DNS/connection
   failures are proof of death. Drop the dead ones by PATCHing the draft; never bulk-delete
   everything that didn't return 200.

6. **If the user wants changes**, they can:
   - Edit the draft at the admin preview page
   - Use the regenerate-with-remarks feature on the preview page
   - Approve it to publish: `curl -X POST http://localhost:8080/api/drafts/<id>/approve`

## Rules for editing prompts

The generation rules live in `backend/data/prompts/`, NOT in Python code:

| File | Purpose |
|------|---------|
| `blog_system.md` | Voice, tone, formatting rules, diagram limits |
| `blog_tool.json` | Structured output schema (title, tags, content, image_query) |
| `blog_review.md` | Quality gate — what the AI slop detector checks for |
| `review_tool.json` | Review output schema (score, verdict, issues, strengths) |
| `sources_system.md` | Source-finding rules — verbatim URLs, which domains to prefer/avoid |
| `sources_tool.json` | `suggest_sources` schema. `minItems` is **0** on purpose: a floor of 3 pressures the model into inventing URLs when search only surfaced one or two real ones. Do not raise it. |

To change generation rules (e.g., allow 2 diagrams, change word count, adjust tone), edit the relevant prompt file. Changes take effect on the next container rebuild.

## Improving quality

- If a topic consistently produces low-quality drafts, edit the topic's `description` or
  `outline` in `daily_topics.json` to give Claude more specific constraints.
- The pipeline automatically feeds review feedback into retry attempts — if the first draft
  fails review, the issues are included in the retry prompt so Claude can fix them.
- System prompts and tool schemas are marked with `cache_control: ephemeral` for Anthropic's
  prompt caching (90% input token discount on cache hits within the 5-minute TTL). Batch
  generation benefits from this automatically. Avoid putting variable content at the start
  of messages — keep it at the end so the cached prefix stays stable.

## Do NOT

- Modify `generate_api.py` to change prompt content — edit the template files instead
- Generate without the API — the pipeline includes image fetching, quality review, and draft persistence
- Approve drafts without reviewing them first
