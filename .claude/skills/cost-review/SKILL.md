---
name: cost-review
description: On-demand analysis of the blog's Claude API spend. Pulls real cost + quality data, fetches CURRENT model pricing and evals (never hardcoded), reads the generation config, and outputs a ranked table of cost-reduction suggestions that weigh output quality. Run manually only.
---

# Cost Review

Analyze where the blog's Claude API money goes and propose reductions — **without
sacrificing output quality**. This runs **on demand only** (it is a manual skill, not a
hook or scheduled job). It changes nothing; it produces an analysis + a suggestions table.
Only apply a change if the user explicitly asks after reviewing.

Two hard rules:
1. **Always use up-to-date pricing and evals** — never trust hardcoded numbers (the app's
   `MODEL_PRICING` map and the pricing table in `blog_system.md` go stale, e.g. intro
   pricing expiries). Fetch current pricing and current model quality/evals every run.
2. **Weigh quality, not just cost** — every suggestion must state its quality impact. Rank by
   *savings × low quality risk*, not raw savings. Never recommend a change that would visibly
   degrade the published blog without flagging it loudly.

## Steps

### 1. Pull the real spend + quality signal (app data)
Fetch the JSON snapshot from the running app (admin-gated). Use dev if it's up, else prod:

```bash
# log in (dev shown; for prod use https://zdenovo.com and the prod admin password)
CJ=$(mktemp); PW=$(grep -E '^ADMIN_PASSWORD=' backend/.env | cut -d= -f2- | tr -d '"'"'"'"')
curl -s -c "$CJ" -X POST http://localhost:8080/admin/login \
  --data-urlencode "password=$PW" --data-urlencode "next=/admin" -o /dev/null
curl -s -b "$CJ" http://localhost:8080/api/costs/summary | python3 -m json.tool
```

The response gives: `by_step` (plan_series/generate/review/sources — calls + cost),
`by_model` (model + calls + cost), `today`/`last7`/`last30`/`all_total`, `recent_days`, and
`quality` (`avg_review_score`, `passing_ge6`, `drafts_scored`). From `by_step` compute each
step's **share of total** and **avg cost/call**; identify the dominant driver.

### 2. Read the current generation config (code, not memory)
- `backend/routers/generate_api.py`: the model in `generate_post` (`model="…"`), the
  `MODEL_PRICING` map, `max_tokens`, `MAX_GENERATION_ATTEMPTS`, `SERIES_GENERATION_ATTEMPTS`,
  and `find_sources`' web-search `max_uses` + whether sources run once-per-series.
- `review_post`, `find_sources`, `plan_series`, `discover_trending_topics`: which model each uses.
- Target post length in `data/prompts/blog_system.md` and `blog_series_system.md`.

### 3. Fetch CURRENT pricing + evals (never hardcode)
- Load the **`claude-api`** skill for current model ids and pricing, and/or `WebFetch`
  Anthropic's pricing page. Confirm the price per input/output MTok for every model in use
  **today**, and flag any intro/promo pricing and its expiry. Compare against the app's
  `MODEL_PRICING` map and note if the map is stale.
- For quality tradeoffs, get **current model evals/positioning** (via the `claude-api`
  reference and/or `WebSearch` for recent benchmarks) — especially for creative long-form
  writing (the `generate` step) vs cheap classification (review/sources/plan). Combine that
  external signal with the app's own `avg_review_score` / `passing_ge6` as an internal eval.

### 4. Output the suggestions table
Rank suggestions by impact × quality-safety. Use this shape:

| # | Lever | Current | Proposed | Est. savings | Quality impact | Effort |
|---|-------|---------|----------|--------------|----------------|--------|

- **Est. savings**: ground it in the actual `by_step`/`by_model` numbers × the *live* prices
  (e.g. "generate is 75% of spend; model X is Np/MTok cheaper on output → ~Y% off generate →
  ~Z% off total"). Show the math briefly.
- **Quality impact**: ✅ none / ⚠️ minor / ❌ material — with one line why, citing the eval
  signal (external benchmarks + the app's review scores).
- Lead with a one-line **recommendation** (the best savings-per-quality-risk move) and a
  **"do not"** (the cheapest option that would hurt quality, called out so it isn't taken blindly).

## Levers catalog (evaluate each against live data)
- **Generation model** (`generate_post`) — usually the biggest lever (output-token heavy).
  Swap only to a model whose *current* evals hold quality for long-form writing; check for
  cheaper intro pricing on a newer model.
- **Generation length** (prompt word targets, `max_tokens`) — output tokens are the cost;
  shorter = cheaper but less depth.
- **Retry attempts** (`MAX_GENERATION_ATTEMPTS`, `SERIES_GENERATION_ATTEMPTS`) — fewer =
  cheaper but risk lower-scored drafts; check `passing_ge6` before cutting.
- **Sources** (`find_sources` `max_uses`, once-per-series scope, or making it optional) —
  web search + large result payloads are pricey; already reduced, confirm it's still worth it.
- **Secondary-task models** (review/sources/plan) — keep on the cheapest capable model
  (Haiku); only worth revisiting if they grow in share.
- **Prompt caching** — confirm the system prompt + corpus stay cache-eligible (stable prefix).

## Do NOT
- Do NOT hardcode or trust stale prices/evals — re-fetch every run.
- Do NOT apply any change automatically — output the table and let the user decide.
- Do NOT recommend a cheaper model/length purely on cost without the quality column.
- Do NOT run this on a schedule — it is on-demand only.
