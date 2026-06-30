"""SEO routes: sitemap, robots.txt, RSS feed."""

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from data.posts import get_all_posts, get_all_tags


router = APIRouter(tags=["seo"])

DOMAIN = "https://zdenovo.com"


@router.get("/sitemap.xml")
async def sitemap() -> Response:
    """Generate XML sitemap for search engines."""
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
        ("/projects/fakturant", "monthly", "0.5"),
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
    for tag in get_all_tags():
        lines.append(
            f"  <url><loc>{DOMAIN}/blog?tag={tag}</loc>"
            f"<changefreq>weekly</changefreq><priority>0.6</priority></url>"
        )
    lines.append("</urlset>")
    return Response(content="\n".join(lines), media_type="application/xml")


@router.get("/robots.txt")
async def robots() -> PlainTextResponse:
    """Generate robots.txt for search engine crawlers."""
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        f"Sitemap: {DOMAIN}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@router.get("/feed.xml")
async def rss_feed() -> Response:
    """Generate RSS feed of latest blog posts."""
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
