"""Dashboard numbers. Each count is a plain SQL query so it can be checked by hand."""
from datetime import timedelta

from . import normalize as N
from .db import Conn

CLOSED = ("Won", "Lost", "Not a fit")


def dashboard(conn: Conn, settings: dict) -> dict:
    min_s = int(settings["min_opportunity_score"])
    high = int(settings["high_opportunity_score"])
    base = "FROM leads WHERE archived = 0"
    q = lambda sql, p=(): conn.scalar(sql, p) or 0  # noqa: E731
    today = N.today().isoformat()
    week_ago = (N.today() - timedelta(days=7)).isoformat()
    counts = {
        "total": q(f"SELECT COUNT(*) {base}"),
        "qualified": q(f"SELECT COUNT(*) {base} AND opportunity_score >= ? AND status <> 'Not a fit'", [min_s]),
        "high_opportunity": q(f"SELECT COUNT(*) {base} AND opportunity_score >= ? AND status <> 'Not a fit'", [high]),
        "unscored": q(f"SELECT COUNT(*) {base} AND opportunity_score IS NULL"),
        "discovered_7d": q(f"SELECT COUNT(*) {base} AND discovered_at >= ?", [week_ago]),
        "followups_due": q(f"SELECT COUNT(*) {base} AND follow_up_at IS NOT NULL AND follow_up_at <= ? AND status NOT IN ('Won','Lost','Not a fit')", [today]),
    }
    funnel_row = conn.one("SELECT COALESCE(SUM(o.contacted),0) AS contacted, COALESCE(SUM(o.responded),0) AS replies, "
                          "COALESCE(SUM(o.interested),0) AS interested, COALESCE(SUM(o.meeting),0) AS meetings, "
                          "COALESCE(SUM(o.proposal),0) AS proposals, COALESCE(SUM(o.purchased),0) AS won, "
                          "COALESCE(SUM(CASE WHEN o.purchased = 1 THEN o.revenue ELSE 0 END),0) AS revenue "
                          "FROM outcomes o JOIN leads l ON l.id = o.lead_id WHERE l.archived = 0") or {}
    counts.update({k: int(v or 0) if k != "revenue" else float(v or 0) for k, v in funnel_row.items()})

    cols = ("id, business_name, industry, city, opportunity_score, kard_fit, business_quality, confidence, status, "
            "top_reason, top_pain, latest_buying_signal, latest_buying_signal_at, follow_up_at, pitch_angle, instagram_url, "
            "tiktok_url, website_url, whatsapp")
    high_list = conn.all(f"SELECT {cols} {base} AND opportunity_score >= ? AND contacted_at IS NULL "
                         "AND status NOT IN ('Won','Lost','Not a fit') ORDER BY opportunity_score DESC, kard_fit DESC LIMIT 8", [high])
    window = (N.today() - timedelta(days=int(settings["buying_signal_window_days"]))).isoformat()
    recent_buying = conn.all(f"SELECT {cols} {base} AND latest_buying_signal_at IS NOT NULL AND latest_buying_signal_at >= ? "
                             "AND status NOT IN ('Won','Lost','Not a fit') ORDER BY latest_buying_signal_at DESC, opportunity_score DESC LIMIT 8", [window])
    follow_ups = conn.all(f"SELECT {cols} {base} AND follow_up_at IS NOT NULL AND follow_up_at <= ? "
                          "AND status NOT IN ('Won','Lost','Not a fit') ORDER BY follow_up_at ASC LIMIT 10",
                          [(N.today() + timedelta(days=2)).isoformat()])
    status_counts = {r["status"]: r["n"] for r in conn.all(f"SELECT status, COUNT(*) AS n {base} GROUP BY status")}
    bands = []
    for lo, hi, label in ((80, 101, "80–100"), (65, 80, "65–79"), (50, 65, "50–64"), (0, 50, "0–49")):
        r = conn.one("SELECT COUNT(*) AS leads, COALESCE(SUM(o.contacted),0) AS contacted, COALESCE(SUM(o.responded),0) AS replied, "
                     "COALESCE(SUM(o.interested),0) AS interested, COALESCE(SUM(o.purchased),0) AS won FROM leads l "
                     "LEFT JOIN outcomes o ON o.lead_id = l.id WHERE l.archived = 0 AND l.opportunity_score >= ? AND l.opportunity_score < ?",
                     [lo, hi])
        bands.append({"band": label, **{k: int(v or 0) for k, v in r.items()}})
    by_industry = conn.all(f"SELECT industry, COUNT(*) AS n, ROUND(AVG(opportunity_score)) AS avg_score {base} "
                           "AND industry <> '' GROUP BY industry ORDER BY n DESC LIMIT 8")
    month = N.today().replace(day=1).isoformat()
    ai = conn.one("SELECT COUNT(*) AS runs, COALESCE(SUM(est_cost_usd),0) AS cost FROM ai_runs WHERE status = 'ok' AND created_at >= ?", [month])
    return {"counts": counts, "high_opportunity": high_list, "recent_buying": recent_buying, "follow_ups": follow_ups,
            "status_counts": status_counts, "score_bands": bands, "by_industry": by_industry,
            "ai_month": {"runs": int(ai["runs"] or 0), "cost_usd": round(float(ai["cost"] or 0), 4)}}
