import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone

from config import read_secret
from db import get_conn

log = logging.getLogger(__name__)


def refresh_popular_posts() -> int:
    """Fetch page view counts from Cloudflare and update the posts.views column.

    Returns the number of posts updated. Logs and returns 0 on failure.
    """
    cf_token = read_secret("cloudflare_api_token", "CLOUDFLARE_API_TOKEN")
    zone_id = os.environ.get("CF_ZONE_ID", "")
    if not cf_token or not zone_id:
        log.info("Cloudflare analytics not configured — skipping view count refresh")
        return 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    query = """
    {
      viewer {
        zones(filter: {zoneTag: "%s"}) {
          httpRequestsAdaptiveGroups(
            limit: 50
            filter: {
              date_geq: "%s"
              date_leq: "%s"
              requestSource: "eyeball"
              clientRequestPath_like: "/blog/%%"
              clientRequestPath_neq: "/blog"
            }
            orderBy: [count_DESC]
          ) {
            dimensions { clientRequestPath }
            count
          }
        }
      }
    }
    """ % (zone_id, month_ago, today)

    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"Bearer {cf_token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        log.warning("Failed to fetch Cloudflare analytics for view counts")
        return 0

    if data.get("errors") or not data.get("data"):
        log.warning("Cloudflare API error: %s", data.get("errors"))
        return 0

    zones = data["data"].get("viewer", {}).get("zones", [{}])
    zone = zones[0] if zones else {}
    rows = zone.get("httpRequestsAdaptiveGroups", [])

    slug_views: dict[str, int] = {}
    for row in rows:
        path = row["dimensions"]["clientRequestPath"]
        slug = path.removeprefix("/blog/").strip("/")
        if not slug:
            continue
        slug_views[slug] = slug_views.get(slug, 0) + row["count"]

    if not slug_views:
        log.info("No blog post views found in Cloudflare data")
        return 0

    updated = 0
    with get_conn() as conn:
        for slug, views in slug_views.items():
            result = conn.execute(
                "UPDATE posts SET views = ? WHERE slug = ?", (views, slug)
            )
            if result.rowcount > 0:
                updated += 1

    log.info("Updated view counts for %d posts", updated)
    return updated
