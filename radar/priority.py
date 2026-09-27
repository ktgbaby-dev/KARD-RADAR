"""TODAY'S 20 — the outreach queue. Transparent priority formula, explained per lead."""
from . import normalize as N
from .db import Conn

ELIGIBLE = ("New", "Researching", "Qualified", "Follow-up", "Contacted")


def priority_for(lead: dict, settings: dict) -> tuple[float, list[str]] | None:
    status = lead["status"]
    if status not in ELIGIBLE or lead.get("opportunity_score") is None:
        return None
    reachable = any(lead.get(k) for k in ("instagram_handle", "tiktok_handle", "whatsapp", "phone", "email"))
    if not reachable:
        return None
    today = N.today()
    fu = N.to_date(lead.get("follow_up_at"))
    follow_due = bool(fu and fu <= today)
    if status == "Contacted" and not follow_due:
        return None  # already contacted and waiting — not today's job unless a follow-up is due
    reasons = []
    opp = lead["opportunity_score"] or 0
    score = opp * 0.55
    reasons.append(f"Opportunity {opp} × 0.55 = {opp * 0.55:.1f}")
    days = N.days_since(lead.get("latest_buying_signal_at"))
    window = int(settings["buying_signal_window_days"])
    if days is not None and days <= 7:
        score += 20
        reasons.append(f"Buying signal {days} day(s) ago +20")
    elif days is not None and days <= window:
        score += 12
        reasons.append(f"Buying signal {days} days ago +12")
    elif (lead.get("buying_signal_count") or 0) > 0:
        score += 4
        reasons.append("Buying signal (undated or older) +4")
    conf = {"High": 10, "Medium": 5}.get(lead.get("confidence") or "", 0)
    if conf:
        score += conf
        reasons.append(f"{lead['confidence']} confidence +{conf}")
    aw = settings["weights"]["accessibility"] or 1
    acc = min(1.0, (lead.get("access_points") or 0) / aw)
    score += acc * 10
    reasons.append(f"Accessibility {acc * 100:.0f}% +{acc * 10:.1f}")
    if follow_due:
        score += 15
        reasons.append("Follow-up due +15")
    return round(score, 1), reasons


def todays_list(conn: Conn, settings: dict, limit: int | None = None) -> list[dict]:
    limit = limit or int(settings.get("today_count", 20))
    rows = conn.all(
        "SELECT id, business_name, industry, subcategory, city, state, instagram_url, instagram_handle, tiktok_url, tiktok_handle, "
        "website_url, website_status, whatsapp, phone, email, status, opportunity_score, kard_fit, business_quality, confidence, "
        "access_points, buying_signal_count, latest_buying_signal_at, latest_buying_signal, top_reason, top_pain, pitch_angle, "
        "follow_up_at, contacted_at, last_contact_channel FROM leads WHERE archived = 0 AND opportunity_score IS NOT NULL "
        f"AND status IN ({', '.join('?' for _ in ELIGIBLE)})", list(ELIGIBLE))
    ranked = []
    min_score = int(settings["min_opportunity_score"])
    for r in rows:
        p = priority_for(r, settings)
        if not p:
            continue
        r["priority"], r["priority_reasons"] = p
        r["below_threshold"] = (r["opportunity_score"] or 0) < min_score
        ranked.append(r)
    ranked.sort(key=lambda r: (-r["priority"], -(r["opportunity_score"] or 0), r["id"]))
    top = ranked[:limit]
    if top:
        ids = [r["id"] for r in top]
        msgs = conn.all(f"SELECT lead_id, channel, subject, body, generator FROM outreach_messages WHERE lead_id IN "
                        f"({', '.join('?' for _ in ids)}) ORDER BY generator ASC", ids)
        by_lead: dict[int, dict] = {}
        for m in msgs:  # 'ai' sorts before 'template', so AI drafts win when present
            by_lead.setdefault(m["lead_id"], {}).setdefault(m["channel"], m)
        for r in top:
            r["outreach"] = by_lead.get(r["id"], {})
    return top
