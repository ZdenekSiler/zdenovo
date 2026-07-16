import json

from db import draft_row_to_dict, get_conn


def get_drafts(status: str | None = None) -> list[dict]:
    """List drafts, optionally filtered by status. status=None returns all."""
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM drafts WHERE status = ? ORDER BY generated_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM drafts ORDER BY generated_at DESC").fetchall()
    return [draft_row_to_dict(r) for r in rows]


def get_drafts_grouped(status: str | None = None) -> dict:
    """Shape the drafts list for the admin review page: series drafts collected under their
    series (parts in order, with completeness + missing slots), and non-series drafts separate.

    Returns {"series_groups": [...], "standalone": [...]}. `status` filters which draft *cards*
    appear (via get_drafts); series completeness always uses the full slate (all drafts + all
    published posts + the planned outline) so "X of N" and missing parts are accurate.
    """
    drafts = get_drafts(status)
    standalone = [d for d in drafts if not d.get("series_id")]
    drafts_in_view: dict[str, dict[int, dict]] = {}   # series_id -> {order -> draft}
    for d in drafts:
        if d.get("series_id"):
            drafts_in_view.setdefault(d["series_id"], {})[d.get("series_order")] = d

    with get_conn() as conn:
        series_rows = {r["id"]: r for r in conn.execute("SELECT id, title, outline FROM series")}
        published = {}                                 # series_id -> {order -> slug}
        for r in conn.execute(
            "SELECT series_id, series_order, slug FROM posts WHERE series_id IS NOT NULL"
        ):
            published.setdefault(r["series_id"], {})[r["series_order"]] = r["slug"]
        # Newest draft per series (any status) — for ordering the groups.
        newest = {r["series_id"]: r["ts"] for r in conn.execute(
            "SELECT series_id, MAX(generated_at) AS ts FROM drafts"
            " WHERE series_id IS NOT NULL GROUP BY series_id"
        )}

    groups = []
    for series_id in drafts_in_view:
        row = series_rows.get(series_id)
        title = row["title"] if row else series_id
        pub = published.get(series_id, {})
        in_view = drafts_in_view[series_id]

        # Outline defines the full slate; fall back to the orders we actually have.
        outline_titles: dict[int, str] = {}
        if row and row["outline"]:
            for p in json.loads(row["outline"]).get("parts", []):
                outline_titles[p["part_number"]] = p["title"]
        orders = set(outline_titles) | set(in_view) | set(pub)
        total = max(orders) if orders else 0

        parts = []
        present = 0
        for order in range(1, total + 1):
            if order in in_view:
                parts.append({"state": "draft", "order": order, "draft": in_view[order]})
                present += 1
            elif order in pub:
                parts.append({"state": "published", "order": order,
                              "title": outline_titles.get(order, ""), "slug": pub[order]})
                present += 1
            elif order in outline_titles:
                parts.append({"state": "missing", "order": order, "title": outline_titles[order]})
        groups.append({
            "series_id": series_id, "series_title": title,
            "present": present, "total": total, "parts": parts,
            "_sort": newest.get(series_id, ""),
        })

    groups.sort(key=lambda g: g["_sort"], reverse=True)
    return {"series_groups": groups, "standalone": standalone}


def get_draft_status_counts() -> dict:
    """Draft counts per status, for the admin filter pills. Only 'pending' and
    'approved' are ever persisted — rejecting a draft deletes the row rather than
    setting a 'rejected' status."""
    with get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) as n FROM drafts GROUP BY status").fetchall()
    counts = {row["status"]: row["n"] for row in rows}
    return {"pending": counts.get("pending", 0), "approved": counts.get("approved", 0), "all": sum(counts.values())}
