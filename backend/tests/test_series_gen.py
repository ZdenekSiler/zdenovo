import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ─── Mock payloads ────────────────────────────────────────────────────────────

PLAN_DATA = {
  "series_title": "Learning LangChain",
  "series_description": "A hands-on tour of LangChain from first principles.",
  "parts": [
    {"part_number": 1, "title": "LangChain Basics", "angle": "Orient a newcomer.",
     "key_points": ["what it is", "install"], "suggested_tags": ["langchain", "python"]},
    {"part_number": 2, "title": "Chains and Prompts", "angle": "Compose prompts.",
     "key_points": ["prompt templates"], "suggested_tags": ["langchain"]},
    {"part_number": 3, "title": "Agents and Tools", "angle": "Wire up tools.",
     "key_points": ["tool calling"], "suggested_tags": ["langchain", "agents"]},
  ],
}

POST_DATA = {
  "title": "LangChain Basics",
  "summary": "A practical intro to LangChain.",
  "tags": ["langchain", "python"],
  "content": "## Intro\n\nLangChain is a framework.\n\n## Setup\n\nInstall it.\n\n## Wrap\n\nDone.",
}


def _mock_client(payload: dict) -> MagicMock:
  tool_block = MagicMock()
  tool_block.type = "tool_use"
  tool_block.input = payload
  message = MagicMock()
  message.content = [tool_block]
  client = MagicMock()
  client.messages.create.return_value = message
  return client


def _mock_client_usage(payload: dict, model: str = "claude-sonnet-4-6", inp: int = 1000, out: int = 2000) -> MagicMock:
  """Mock client whose responses carry realistic token usage, so cost recording runs."""
  tool_block = MagicMock()
  tool_block.type = "tool_use"
  tool_block.input = payload
  usage = MagicMock()
  usage.input_tokens = inp
  usage.output_tokens = out
  usage.cache_read_input_tokens = 0
  usage.cache_creation_input_tokens = 0
  usage.server_tool_use = None
  message = MagicMock()
  message.content = [tool_block]
  message.usage = usage
  message.model = model
  client = MagicMock()
  client.messages.create.return_value = message
  return client


# ─── Cost tracking ────────────────────────────────────────────────────────────

def test_compute_cost_math():
  from routers.generate_api import _compute_cost
  # 1000 input + 2000 output on Sonnet 4.6 = (1000*3 + 2000*15)/1e6 = 0.033
  assert _compute_cost("claude-sonnet-4-6", 1000, 2000, 0, 0, 0) == round(0.033, 6)
  # Sonnet 5 intro pricing = (1000*2 + 2000*10)/1e6 = 0.022
  assert _compute_cost("claude-sonnet-5", 1000, 2000, 0, 0, 0) == round(0.022, 6)
  # web searches add $0.01 each
  assert _compute_cost("claude-haiku-4-5-20251001", 0, 0, 0, 0, 2) == round(0.02, 6)


def test_generation_records_api_cost_row(test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import blog_generator
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client_usage(POST_DATA)):
    blog_generator.generate_post("write a post")
  import db
  with db.get_conn() as conn:
    row = conn.execute("SELECT step, cost_usd FROM api_costs ORDER BY created_at DESC LIMIT 1").fetchone()
  assert row is not None and row["cost_usd"] > 0


def test_draft_stores_gen_cost(test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import blog_generator, _insert_draft
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client_usage(POST_DATA)):
    post, review = blog_generator.generate_with_review("write", max_attempts=1, with_sources=False)
    draft = _insert_draft(post, topic_id="freeform", review=review)
  assert draft.gen_cost_usd is not None and draft.gen_cost_usd > 0


def test_series_runs_find_sources_once(test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import blog_generator, generate_series, SeriesPart
  parts = [SeriesPart(part_number=i, title=f"P{i}", angle="a", key_points=["x"], suggested_tags=["t"]) for i in (1, 2, 3)]
  calls = {"n": 0}
  monkeypatch.setattr(blog_generator, "find_sources", lambda post: calls.__setitem__("n", calls["n"] + 1) or [])
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client_usage(POST_DATA)):
    generate_series("s", "S", parts)
  assert calls["n"] == 1  # once for the whole series, not once per part


# ─── Schema migration ─────────────────────────────────────────────────────────

def test_init_db_adds_series_id_column_to_drafts(test_db):
  import db
  with db.get_conn() as conn:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(drafts)")}
  assert "series_id" in cols


def test_init_db_adds_series_order_column_to_drafts(test_db):
  import db
  with db.get_conn() as conn:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(drafts)")}
  assert "series_order" in cols


# ─── Planner ──────────────────────────────────────────────────────────────────

def test_plan_series_returns_parts_for_requested_count(test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import blog_generator
  series_type = {"label": "Deep dive", "arc_guidance": "go deep", "part_guidance": "each deeper"}
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client(PLAN_DATA)):
    plan = blog_generator.plan_series("LangChain", series_type, count=2)
  assert len(plan.parts) == 2
  assert [p.part_number for p in plan.parts] == [1, 2]
  assert plan.series_title == "Learning LangChain"


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def test_generate_series_inserts_one_draft_per_part(test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import SeriesPart, generate_series
  parts = [
    SeriesPart(part_number=1, title="Part One", angle="a", key_points=["x"], suggested_tags=["t"]),
    SeriesPart(part_number=2, title="Part Two", angle="b", key_points=["y"], suggested_tags=["t"]),
  ]
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client(POST_DATA)):
    generate_series("learning-langchain", "Learning LangChain", parts)
  import db
  with db.get_conn() as conn:
    rows = conn.execute(
      "SELECT series_id, series_order, topic_id FROM drafts ORDER BY series_order"
    ).fetchall()
  assert len(rows) == 2


def test_generated_drafts_carry_series_id_and_order(test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import SeriesPart, generate_series
  parts = [
    SeriesPart(part_number=1, title="Part One", angle="a", key_points=["x"], suggested_tags=["t"]),
    SeriesPart(part_number=2, title="Part Two", angle="b", key_points=["y"], suggested_tags=["t"]),
  ]
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client(POST_DATA)):
    generate_series("learning-langchain", "Learning LangChain", parts)
  import db
  with db.get_conn() as conn:
    rows = conn.execute(
      "SELECT series_id, series_order, topic_id FROM drafts ORDER BY series_order"
    ).fetchall()
  assert [dict(r)["series_id"] for r in rows] == ["learning-langchain", "learning-langchain"]
  assert [dict(r)["series_order"] for r in rows] == [1, 2]
  assert all(dict(r)["topic_id"] == "series:learning-langchain" for r in rows)


# ─── Endpoint ─────────────────────────────────────────────────────────────────

def test_generate_series_endpoint_returns_202_with_outline(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  # Patch the source attribute so the lazy `from ... import generate_series` picks up the mock,
  # keeping the fire-and-forget background generation out of this planning-only test.
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client(PLAN_DATA)), \
       patch("routers.generate_api.generate_series") as mock_gen:
    resp = admin_client.post(
      "/api/series/generate",
      json={"topic": "LangChain", "series_type": "deep-dive", "parts": 3},
    )
  assert resp.status_code == 202
  body = resp.json()
  assert body["series_title"] == "Learning LangChain"
  assert len(body["parts"]) == 3
  assert mock_gen.called


def test_generate_series_endpoint_creates_series_row(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client(PLAN_DATA)), \
       patch("routers.generate_api.generate_series"):
    resp = admin_client.post(
      "/api/series/generate",
      json={"topic": "LangChain", "series_type": "deep-dive", "parts": 3},
    )
  series_id = resp.json()["series_id"]
  listed = {s["id"] for s in admin_client.get("/api/series").json()}
  assert series_id in listed


def test_generate_series_derives_short_id_from_topic_and_type(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client(PLAN_DATA)), \
       patch("routers.generate_api.generate_series"):
    resp = admin_client.post(
      "/api/series/generate",
      json={"topic": "LangChain", "series_type": "deep-dive", "parts": 2},
    )
  assert resp.status_code == 202
  # id comes from topic+type, not the planner's verbose title
  assert resp.json()["series_id"] == "langchain-deep-dive"


def test_series_parts_use_the_series_prompt_and_tool(test_db, monkeypatch):
  # Series parts are written with the distinct chapter prompt (no Mermaid, chapter structure),
  # not the standalone blog_system prompt.
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import blog_generator
  mock = _mock_client(POST_DATA)
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock):
    blog_generator.generate_post("Write part 2.", series=True)
  kwargs = mock.messages.create.call_args.kwargs
  system_text = kwargs["system"][0]["text"]
  assert "series" in system_text.lower() and "Key takeaways" in system_text
  # the distinct tool's content spec forbids Mermaid
  content_desc = kwargs["tools"][0]["input_schema"]["properties"]["content"]["description"]
  assert "Mermaid" in content_desc


def test_standalone_posts_use_the_default_prompt(test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import blog_generator
  mock = _mock_client(POST_DATA)
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock):
    blog_generator.generate_post("Write a one-off post.", series=False)
  system_text = mock.messages.create.call_args.kwargs["system"][0]["text"]
  assert "war stories" in system_text.lower()  # the standalone voice prompt


def test_series_progress_reports_pending_and_published_parts(admin_client):
  import db
  now = datetime.now(timezone.utc).isoformat()
  with db.get_conn() as conn:
    conn.execute("INSERT INTO series (id, title, description, created_at) VALUES (?,?,?,?)",
                 ("s1", "S1", "d", now))
    # part 1 published, part 2 still a pending draft
    conn.execute("INSERT INTO posts (slug, title, date, summary, tags, content, series_id, series_order)"
                 " VALUES (?,?,?,?,?,?,?,?)",
                 ("s1-part-1", "Part One", "2026-07-15", "s", '["t"]', "body", "s1", 1))
    conn.execute("INSERT INTO drafts (id, slug, title, date, summary, tags, content, generated_at,"
                 " topic_id, status, sources, series_id, series_order)"
                 " VALUES (?,?,?,?,?,?,?,?,?,'pending','[]',?,?)",
                 ("d2", "s1-part-2", "Part Two", "2026-07-15", "s", '["t"]', "body", now, "series:s1", "s1", 2))
  r = admin_client.get("/api/series/s1/progress")
  assert r.status_code == 200
  parts = r.json()["parts"]
  assert [p["series_order"] for p in parts] == [1, 2]
  assert parts[0]["status"] == "published" and parts[0]["ref"] == "/blog/s1-part-1"
  assert parts[1]["status"] == "pending" and parts[1]["ref"] == "/admin/drafts/d2"


def test_series_progress_requires_admin(client):
  r = client.get("/api/series/whatever/progress", follow_redirects=False)
  assert r.status_code == 303


def _seed_series_with_outline(series_id: str, total: int) -> None:
  import db
  parts = [{"part_number": i, "title": f"P{i}", "angle": "a", "key_points": ["x"], "suggested_tags": ["t"]}
           for i in range(1, total + 1)]
  with db.get_conn() as conn:
    conn.execute(
      "INSERT INTO series (id, title, description, created_at, outline) VALUES (?,?,?,?,?)",
      (series_id, series_id.upper(), "d", "2026-07-15",
       json.dumps({"total": total, "parts": parts})),
    )


def test_generate_series_stores_outline(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client(PLAN_DATA)), \
       patch("routers.generate_api.generate_series"):
    resp = admin_client.post("/api/series/generate", json={"topic": "LangChain", "series_type": "deep-dive", "parts": 3})
  sid = resp.json()["series_id"]
  import db
  with db.get_conn() as conn:
    row = conn.execute("SELECT outline FROM series WHERE id = ?", (sid,)).fetchone()
  outline = json.loads(row["outline"])
  assert outline["total"] == 3 and len(outline["parts"]) == 3


def test_generate_part_creates_draft_from_outline(test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import SeriesPart, generate_series_part
  _seed_series_with_outline("s1", 2)
  parts = [SeriesPart(part_number=i, title=f"P{i}", angle="a", key_points=["x"], suggested_tags=["t"]) for i in (1, 2)]
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client_usage(POST_DATA)):
    generate_series_part("s1", "S1", parts, 2)
  import db
  with db.get_conn() as conn:
    rows = conn.execute("SELECT series_order, status FROM drafts WHERE series_id = 's1'").fetchall()
  assert any(r["series_order"] == 2 and r["status"] == "pending" for r in rows)


def test_generate_part_endpoint_202(admin_client):
  _seed_series_with_outline("s3", 2)
  with patch("routers.generate_api.generate_series_part"):
    r = admin_client.post("/api/series/s3/parts/2/generate")
  assert r.status_code == 202
  assert r.json()["part_number"] == 2


def test_add_series_part_appends_to_outline_and_generates(admin_client):
  _seed_series_with_outline("s5", 2)
  with patch("routers.generate_api.generate_series_part") as mock_gen:
    r = admin_client.post("/api/series/s5/parts", json={
      "title": "Comparison Part", "angle": "vs others", "key_points": ["a"], "suggested_tags": ["x"],
    })
  assert r.status_code == 202
  assert r.json()["part_number"] == 3  # appended after the 2 existing
  assert mock_gen.called
  import db
  with db.get_conn() as conn:
    outline = json.loads(conn.execute("SELECT outline FROM series WHERE id='s5'").fetchone()["outline"])
  assert outline["total"] == 3
  assert outline["parts"][-1]["title"] == "Comparison Part"


def test_add_series_part_unknown_series_404(admin_client):
  assert admin_client.post("/api/series/nope/parts", json={"title": "X"}).status_code == 404


def test_add_series_part_requires_admin(client):
  assert client.post("/api/series/x/parts", json={"title": "X"}, follow_redirects=False).status_code == 303


def test_generate_part_endpoint_unknown_series_404(admin_client):
  assert admin_client.post("/api/series/nope/parts/1/generate").status_code == 404


def test_generate_part_endpoint_unknown_part_404(admin_client):
  _seed_series_with_outline("s4", 1)
  assert admin_client.post("/api/series/s4/parts/9/generate").status_code == 404


def test_generate_part_endpoint_requires_admin(client):
  assert client.post("/api/series/x/parts/1/generate", follow_redirects=False).status_code == 303


def test_generate_series_endpoint_rejects_unknown_type(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  resp = admin_client.post(
    "/api/series/generate",
    json={"topic": "LangChain", "series_type": "not-a-real-type"},
  )
  assert resp.status_code == 400


def test_generate_series_endpoint_requires_admin(client):
  resp = client.post(
    "/api/series/generate",
    json={"topic": "LangChain", "series_type": "deep-dive"},
    follow_redirects=False,
  )
  assert resp.status_code == 303


# ─── Approval carries series through ──────────────────────────────────────────

def test_approve_draft_copies_series_id_and_order_into_post(admin_client):
  import db
  draft_id = str(uuid.uuid4())
  now = datetime.now(timezone.utc).isoformat()
  with db.get_conn() as conn:
    conn.execute(
      "INSERT INTO series (id, title, description, created_at) VALUES (?,?,?,?)",
      ("my-series", "My Series", "desc", now),
    )
    conn.execute(
      """INSERT INTO drafts
         (id, slug, title, date, summary, tags, content, image, generated_at, topic_id, status,
          sources, series_id, series_order)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '[]', ?, ?)""",
      (draft_id, "part-one", "Part One", "2026-07-15", "sum", json.dumps(["t"]),
       "## Body\n\nText.", None, now, "series:my-series", "my-series", 1),
    )
  resp = admin_client.post(f"/api/drafts/{draft_id}/approve")
  assert resp.status_code in (200, 201)
  post = admin_client.get("/api/posts/part-one").json()
  assert post["series_id"] == "my-series"
  assert post["series_order"] == 1


# ─── Cost levers ──────────────────────────────────────────────────────────────

def test_generate_post_sends_corpus_as_cached_system_block(test_db, monkeypatch):
  # #1: the existing-posts corpus rides in a cached system block (reused at a discount
  # across a series' parts), not re-sent uncached in every per-call user message.
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import blog_generator
  mock = _mock_client(POST_DATA)
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock):
    blog_generator.generate_post("Write about testing.")
  kwargs = mock.messages.create.call_args.kwargs
  corpus_blocks = [b for b in kwargs["system"] if "<existing_posts>" in b["text"]]
  assert corpus_blocks, "corpus should be sent as a system block"
  assert corpus_blocks[0]["cache_control"] == {"type": "ephemeral"}
  # and not duplicated into the (uncached) user message
  assert "<existing_posts>" not in kwargs["messages"][0]["content"]


def test_series_generation_attempts_capped():
  from routers.generate_api import MAX_GENERATION_ATTEMPTS, SERIES_GENERATION_ATTEMPTS
  # Series never retries more than one-off generation (both are cost-capped at 2).
  assert SERIES_GENERATION_ATTEMPTS <= MAX_GENERATION_ATTEMPTS


def test_generate_series_caps_retry_attempts(test_db, monkeypatch):
  # #2: series parts run with the reduced attempt cap so a failing review can't multiply
  # Sonnet regenerations across every part.
  from datetime import date as D
  from routers.generate_api import (
    PostOut, ReviewResult, SeriesPart, SERIES_GENERATION_ATTEMPTS, blog_generator, generate_series,
  )
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  parts = [SeriesPart(part_number=1, title="P1", angle="a", key_points=["x"], suggested_tags=["t"])]
  fake_post = PostOut(
    slug="p1", title="P1", summary="s", tags=["t"], content="## H\n\ntext",
    date=D.today(), image=None, reading_time=1, sources=[],
  )
  fake_review = ReviewResult(score=8, verdict="pass", issues=[], strengths=[])
  gwr = MagicMock(return_value=(fake_post, fake_review))
  monkeypatch.setattr(blog_generator, "generate_with_review", gwr)
  generate_series("s", "S", parts)
  assert gwr.call_args.kwargs.get("max_attempts") == SERIES_GENERATION_ATTEMPTS
