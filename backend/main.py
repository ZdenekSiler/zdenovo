import json
import os
import re
import secrets
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mistune
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()  # no-op if .env absent; prod uses file secrets

from config import read_secret
from data.posts import get_all_posts, get_all_tags, get_post_by_slug, get_posts_page, get_related_posts, total_pages
from data.projects import get_all_projects
from db import comment_row_to_dict, draft_row_to_dict, get_conn, init_db
from routers.comments_api import router as comments_router
from routers.drafts_api import _regenerate_draft, generate_daily_drafts, router as drafts_router
from routers.generate_api import router as generate_router
from routers.posts_api import router as posts_router
from routers.topics_api import router as topics_router

BASE_DIR = Path(__file__).parent.parent  # zdenovo/


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(generate_daily_drafts, "cron", hour=2, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Zdenovo API",
    description="Blog platform API — posts, drafts, comments, topics, and AI generation.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=read_secret("secret_key", "SECRET_KEY") or "dev-insecure-key-change-in-prod",
    session_cookie="zdenovo_session",
    max_age=60 * 60 * 24 * 7,  # 7 days
    https_only=False,           # set True in prod behind HTTPS
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend" / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "frontend" / "templates")

app.include_router(comments_router)
app.include_router(drafts_router)
app.include_router(generate_router)
app.include_router(posts_router)
app.include_router(topics_router)


def _fmt_date(d) -> str:
    """Cross-platform date format — %-d is Linux-only."""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


templates.env.filters["dateformat"] = _fmt_date
templates.env.filters["markdown"] = mistune.html


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _is_admin(request: Request) -> bool:
    return request.session.get("admin") is True


def require_admin(request: Request) -> None:
    if not _is_admin(request):
        raise _AdminRequired(next_url=str(request.url.path))


class _AdminRequired(Exception):
    def __init__(self, next_url: str = "/admin/posts"):
        self.next_url = next_url


@app.exception_handler(_AdminRequired)
async def _admin_required_handler(request: Request, exc: _AdminRequired):
    return RedirectResponse(f"/admin/login?next={exc.next_url}", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, next: str = "/admin/posts"):
    if _is_admin(request):
        return RedirectResponse(next, status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {"next": next})


@app.post("/admin/login")
async def admin_login(
    request: Request,
    password: str = Form(...),
    next: str = Form("/admin/posts"),
):
    admin_password = read_secret("admin_password", "ADMIN_PASSWORD")
    if admin_password and secrets.compare_digest(password.encode(), admin_password.encode()):
        request.session["admin"] = True
        return RedirectResponse(next if next.startswith("/admin") else "/admin/posts", status_code=303)
    return templates.TemplateResponse(
        request, "admin_login.html", {"next": next, "error": "Wrong password."},
        status_code=401,
    )


@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# ─── HTML pages ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    posts = get_all_posts()[:3]
    projects = [p for p in get_all_projects() if p["featured"]]
    tags = get_all_tags()
    return templates.TemplateResponse(request, "index.html", {
        "recent_posts": posts,
        "featured_projects": projects,
        "all_tags": tags,
    })


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    projects = [p for p in get_all_projects() if p["featured"]]
    tags = get_all_tags()
    return templates.TemplateResponse(request, "about.html", {
        "featured_projects": projects,
        "all_tags": tags,
    })


@app.get("/projects", response_class=HTMLResponse)
async def projects(request: Request):
    return templates.TemplateResponse(
        request, "projects.html", {"projects": get_all_projects()}
    )


@app.get("/blog", response_class=HTMLResponse)
async def blog(request: Request, tag: str | None = None, page: int = 1):
    posts, total = get_posts_page(page, tag=tag)
    n_pages = total_pages(total)
    return templates.TemplateResponse(
        request, "blog.html", {
            "posts": posts,
            "all_tags": get_all_tags(),
            "current_tag": tag,
            "page": page,
            "total_pages": n_pages,
        }
    )


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def post(request: Request, slug: str):
    article = get_post_by_slug(slug)
    if article is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM comments WHERE post_slug = ? ORDER BY created_at ASC", (slug,)
        ).fetchall()
    comments = [comment_row_to_dict(r) for r in rows]
    related = get_related_posts(slug, article["tags"])
    return templates.TemplateResponse(request, "post.html", {
        "post": article, "comments": comments, "slug": slug, "related_posts": related,
    })


@app.post("/blog/{slug}/comments", response_class=HTMLResponse)
async def submit_comment(request: Request, slug: str, author: str = Form(...), body: str = Form(...)):
    article = get_post_by_slug(slug)
    if article is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    if author.strip() and body.strip():
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO comments (id, post_slug, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), slug, author.strip()[:80], body.strip()[:2000], datetime.now(timezone.utc).isoformat()),
            )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM comments WHERE post_slug = ? ORDER BY created_at ASC", (slug,)
        ).fetchall()
    comments = [comment_row_to_dict(r) for r in rows]
    return templates.TemplateResponse(request, "comments_section.html", {"comments": comments, "slug": slug})


# ─── SEO: sitemap, robots.txt, RSS ───────────────────────────────────────────

DOMAIN = "https://zdenovo.com"


@app.get("/sitemap.xml")
async def sitemap():
    posts = get_all_posts()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    static_pages = [
        ("", "weekly", "1.0"),
        ("/blog", "daily", "0.9"),
        ("/about", "monthly", "0.7"),
        ("/projects", "monthly", "0.6"),
    ]
    for path, freq, prio in static_pages:
        lines.append(
            f"  <url><loc>{DOMAIN}{path}</loc>"
            f"<changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
        )
    for p in posts:
        date = p["date"].isoformat() if hasattr(p["date"], "isoformat") else str(p["date"])
        lines.append(
            f"  <url><loc>{DOMAIN}/blog/{p['slug']}</loc>"
            f"<lastmod>{date}</lastmod><changefreq>monthly</changefreq>"
            f"<priority>0.8</priority></url>"
        )
    lines.append("</urlset>")
    return Response(content="\n".join(lines), media_type="application/xml")


@app.get("/robots.txt")
async def robots():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        f"Sitemap: {DOMAIN}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@app.get("/feed.xml")
async def rss_feed():
    posts = get_all_posts()[:20]
    items = []
    for p in posts:
        date = p["date"].isoformat() if hasattr(p["date"], "isoformat") else str(p["date"])
        title = p["title"].replace("&", "&amp;").replace("<", "&lt;")
        summary = (p["summary"] or "").replace("&", "&amp;").replace("<", "&lt;")
        items.append(
            f"    <item>\n"
            f"      <title>{title}</title>\n"
            f"      <link>{DOMAIN}/blog/{p['slug']}</link>\n"
            f"      <guid>{DOMAIN}/blog/{p['slug']}</guid>\n"
            f"      <pubDate>{date}</pubDate>\n"
            f"      <description>{summary}</description>\n"
            f"    </item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        "    <title>Zdenovo Blog</title>\n"
        f"    <link>{DOMAIN}/blog</link>\n"
        "    <description>Notes on software engineering, AI development, and tooling.</description>\n"
        "    <language>en</language>\n"
        f'    <atom:link href="{DOMAIN}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        + "\n".join(items) + "\n"
        "  </channel>\n"
        "</rss>"
    )
    return Response(content=xml, media_type="application/rss+xml")


# ─── Admin pages ──────────────────────────────────────────────────────────────

@app.get("/admin/", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
async def admin_root(request: Request, _: None = Depends(require_admin)):
    posts = get_all_posts()
    with get_conn() as conn:
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE status = 'pending'"
        ).fetchone()[0]
        comment_count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    topic_count = len(_load_topics())
    return templates.TemplateResponse(request, "admin_hub.html", {
        "post_count": len(posts),
        "pending_count": pending_count,
        "comment_count": comment_count,
        "topic_count": topic_count,
    })


@app.get("/admin/posts", response_class=HTMLResponse)
async def admin_posts(request: Request, _: None = Depends(require_admin)):
    posts = get_all_posts()
    with get_conn() as conn:
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE status = 'pending'"
        ).fetchone()[0]
        comment_count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    return templates.TemplateResponse(request, "admin_posts.html", {
        "posts": posts,
        "pending_count": pending_count,
        "comment_count": comment_count,
    })


@app.get("/admin/drafts", response_class=HTMLResponse)
async def admin_drafts(request: Request, _: None = Depends(require_admin)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts ORDER BY generated_at DESC"
        ).fetchall()
    drafts = [draft_row_to_dict(r) for r in rows]
    return templates.TemplateResponse(request, "drafts_list.html", {"drafts": drafts})


@app.get("/admin/drafts/{draft_id}", response_class=HTMLResponse)
async def admin_draft_preview(request: Request, draft_id: str, _: None = Depends(require_admin)):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    draft = draft_row_to_dict(row)
    return templates.TemplateResponse(request, "draft_preview.html", {"draft": draft})


@app.get("/admin/comments", response_class=HTMLResponse)
async def admin_comments(request: Request, _: None = Depends(require_admin)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM comments ORDER BY created_at DESC"
        ).fetchall()
    comments = [comment_row_to_dict(r) for r in rows]
    return templates.TemplateResponse(request, "admin_comments.html", {"comments": comments})


@app.post("/admin/drafts/{draft_id}", response_class=HTMLResponse)
async def admin_draft_edit(
    request: Request,
    draft_id: str,
    title: str = Form(...),
    summary: str = Form(...),
    content: str = Form(...),
    tags: str = Form(""),
    _: None = Depends(require_admin),
):
    tags_list = [t.strip() for t in tags.split(",") if t.strip()]
    with get_conn() as conn:
        conn.execute(
            "UPDATE drafts SET title=?, summary=?, content=?, tags=? WHERE id=?",
            (title, summary, content, json.dumps(tags_list), draft_id),
        )
    return RedirectResponse(f"/admin/drafts/{draft_id}", status_code=303)


@app.post("/admin/drafts/{draft_id}/regenerate", response_class=HTMLResponse)
async def admin_draft_regenerate(
    request: Request,
    draft_id: str,
    remarks: str = Form(...),
    _: None = Depends(require_admin),
):
    _regenerate_draft(draft_id, remarks)
    return RedirectResponse(f"/admin/drafts/{draft_id}", status_code=303)


@app.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(request: Request, _: None = Depends(require_admin)):
    cf_token = read_secret("cloudflare_api_token", "CLOUDFLARE_API_TOKEN")
    zone_id = os.environ.get("CF_ZONE_ID", "")

    if not cf_token or not zone_id:
        return templates.TemplateResponse(request, "admin_stats.html", {"error": "Analytics not configured. Set CLOUDFLARE_API_TOKEN and CF_ZONE_ID."})

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%d")

    query = """
    {
      viewer {
        zones(filter: {zoneTag: "%s"}) {
          daily: httpRequests1dGroups(
            limit: 7
            filter: {date_geq: "%s", date_leq: "%s"}
          ) {
            dimensions { date }
            sum { requests pageViews }
            uniq { uniques }
          }
          topPaths: httpRequestsAdaptiveGroups(
            limit: 10
            filter: {date_geq: "%s", date_leq: "%s", requestSource: "eyeball"}
            orderBy: [count_DESC]
          ) {
            dimensions { clientRequestPath }
            count
          }
          topCountries: httpRequestsAdaptiveGroups(
            limit: 10
            filter: {date_geq: "%s", date_leq: "%s", requestSource: "eyeball"}
            orderBy: [count_DESC]
          ) {
            dimensions { clientCountryName }
            count
          }
          topBrowsers: httpRequestsAdaptiveGroups(
            limit: 5
            filter: {date_geq: "%s", date_leq: "%s", requestSource: "eyeball"}
            orderBy: [count_DESC]
          ) {
            dimensions { userAgent }
            count
          }
        }
      }
    }
    """ % (zone_id, week_ago, today, today, today, today, today, today, today)

    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"Bearer {cf_token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return templates.TemplateResponse(request, "admin_stats.html", {"error": "Failed to fetch analytics from Cloudflare."})

    if data.get("errors") or not data.get("data"):
        msg = data.get("errors", [{}])[0].get("message", "Unknown error") if data.get("errors") else "Empty response"
        return templates.TemplateResponse(request, "admin_stats.html", {"error": f"Cloudflare API error: {msg}"})

    zones = data["data"].get("viewer", {}).get("zones", [{}])
    zone = zones[0] if zones else {}

    daily_raw = zone.get("daily", [])
    daily = sorted(
        [
            {
                "date": d["dimensions"]["date"],
                "page_views": d["sum"]["pageViews"],
                "requests": d["sum"]["requests"],
                "uniques": d["uniq"]["uniques"],
            }
            for d in daily_raw
        ],
        key=lambda d: d["date"],
    )
    max_views = max((d["page_views"] for d in daily), default=1) or 1
    max_uniques = max((d["uniques"] for d in daily), default=1) or 1
    for d in daily:
        d["views_pct"] = round(d["page_views"] / max_views * 100)
        d["uniques_pct"] = round(d["uniques"] / max_uniques * 100)
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        d["day_label"] = dt.strftime("%a")
        d["date_label"] = dt.strftime("%b %d")

    totals = {
        "page_views": sum(d["page_views"] for d in daily),
        "uniques": sum(d["uniques"] for d in daily),
        "requests": sum(d["requests"] for d in daily),
    }

    top_pages = [{"path": r["dimensions"]["clientRequestPath"], "count": r["count"]} for r in zone.get("topPaths", [])]
    top_countries = [{"country": r["dimensions"]["clientCountryName"], "count": r["count"]} for r in zone.get("topCountries", [])]
    top_browsers = [{"browser": r["dimensions"]["userAgent"], "count": r["count"]} for r in zone.get("topBrowsers", [])]

    return templates.TemplateResponse(request, "admin_stats.html", {
        "daily": daily,
        "totals": totals,
        "top_pages": top_pages,
        "top_countries": top_countries,
        "top_browsers": top_browsers,
    })


# ─── Topics management ──────────────────────────────────────────────────────

from routers.topics_api import _load_topics, _save_topics, _slugify


@app.get("/admin/topics", response_class=HTMLResponse)
async def admin_topics(request: Request, _: None = Depends(require_admin)):
    topics = _load_topics()
    return templates.TemplateResponse(request, "admin_topics.html", {"topics": topics})


@app.get("/admin/topics/new", response_class=HTMLResponse)
async def admin_topic_new(request: Request, _: None = Depends(require_admin)):
    return templates.TemplateResponse(request, "admin_topic_edit.html", {"topic": None})


@app.get("/admin/topics/{topic_id}/edit", response_class=HTMLResponse)
async def admin_topic_edit(request: Request, topic_id: str, _: None = Depends(require_admin)):
    topics = _load_topics()
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if topic is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(request, "admin_topic_edit.html", {"topic": topic})


@app.post("/admin/topics", response_class=HTMLResponse)
async def admin_topic_create(
    request: Request,
    title_hint: str = Form(...),
    description: str = Form(...),
    audience: str = Form(...),
    tone: str = Form(...),
    tags: str = Form(""),
    outline: str = Form(""),
    _: None = Depends(require_admin),
):
    topics = _load_topics()
    topic_id = _slugify(title_hint)
    if any(t["id"] == topic_id for t in topics):
        topic_id = f"{topic_id}-{len(topics)}"
    topic = {
        "id": topic_id,
        "title_hint": title_hint.strip(),
        "description": description.strip(),
        "audience": audience.strip(),
        "tone": tone.strip(),
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "outline": [line.strip() for line in outline.splitlines() if line.strip()],
    }
    topics.append(topic)
    _save_topics(topics)
    return RedirectResponse("/admin/topics", status_code=303)


@app.post("/admin/topics/{topic_id}", response_class=HTMLResponse)
async def admin_topic_update(
    request: Request,
    topic_id: str,
    title_hint: str = Form(...),
    description: str = Form(...),
    audience: str = Form(...),
    tone: str = Form(...),
    tags: str = Form(""),
    outline: str = Form(""),
    _: None = Depends(require_admin),
):
    topics = _load_topics()
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if topic is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    topic["title_hint"] = title_hint.strip()
    topic["description"] = description.strip()
    topic["audience"] = audience.strip()
    topic["tone"] = tone.strip()
    topic["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    topic["outline"] = [line.strip() for line in outline.splitlines() if line.strip()]
    _save_topics(topics)
    return RedirectResponse("/admin/topics", status_code=303)


@app.post("/admin/topics/{topic_id}/delete", response_class=HTMLResponse)
async def admin_topic_delete(request: Request, topic_id: str, _: None = Depends(require_admin)):
    topics = _load_topics()
    topics = [t for t in topics if t["id"] != topic_id]
    _save_topics(topics)
    return RedirectResponse("/admin/topics", status_code=303)
