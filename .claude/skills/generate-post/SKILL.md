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

5. **If the user wants changes**, they can:
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

To change generation rules (e.g., allow 2 diagrams, change word count, adjust tone), edit the relevant prompt file. Changes take effect on the next container rebuild.

## Do NOT

- Modify `generate_api.py` to change prompt content — edit the template files instead
- Generate without the API — the pipeline includes image fetching, quality review, and draft persistence
- Approve drafts without reviewing them first
