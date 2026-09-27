"""Lead repository: normalization on write, filters, CRM status tracking and outcome (learning) records."""
from datetime import timedelta

from . import normalize as N
from .db import Conn, dumps, loads
from .dedupe import find_duplicates
from .settings import match_industry

STATUSES = ["New", "Researching", "Qualified", "Contacted", "Replied", "Interested", "Call/Meeting",
            "Proposal", "Won", "Lost", "Not a fit", "Follow-up"]
CLOSED = {"Won", "Lost", "Not a fit"}
IN_CONVERSATION = {"Replied", "Interested", "Call/Meeting", "Proposal"}
CHANNELS = ["instagram", "tiktok", "whatsapp", "email", "phone", "in_person", "other"]

# Status -> outcome flags that become true (cumulative funnel)
STATUS_OUTCOME = {
    "Contacted": ["contacted"], "Follow-up": ["contacted"], "Replied": ["contacted", "responded"],
    "Interested": ["contacted", "responded", "interested"],
    "Call/Meeting": ["contacted", "responded", "interested", "meeting"],
    "Proposal": ["contacted", "responded", "interested", "meeting", "proposal"],
    "Won": ["contacted", "responded", "interested", "purchased"], "Lost": ["lost"],
}

EDITABLE = ["business_name", "industry", "subcategory", "city", "state", "country", "instagram_url", "tiktok_url",
            "website_url", "link_in_bio_url", "whatsapp", "phone", "email", "founder_name", "address", "notes",
            "followers_instagram", "followers_tiktok", "followers_source", "profile_bio", "other_socials",
            "status", "follow_up_at", "no_website_confirmed", "no_link_in_bio"]


class DuplicateError(Exception):
    def __init__(self, matches):
        super().__init__("Possible duplicate")
        self.matches = matches


class ValidationError(ValueError):
    pass


def _int_or_none(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    n = N.parse_count(str(v))
    return n


def prepare(data: dict, settings: dict, existing: dict | None = None) -> dict:
    """Normalize user/CSV/discovery input into lead columns. Only keys present in `data` are returned."""
    out: dict = {}
    d = {k: v for k, v in data.items() if k in EDITABLE or k in ("instagram", "tiktok", "website", "source")}
    if "instagram" in d and "instagram_url" not in d:
        d["instagram_url"] = d.pop("instagram")
    if "tiktok" in d and "tiktok_url" not in d:
        d["tiktok_url"] = d.pop("tiktok")
    if "website" in d and "website_url" not in d:
        d["website_url"] = d.pop("website")

    if "business_name" in d:
        out["business_name"] = N.clean_text(d["business_name"], 160)

    if "instagram_url" in d:
        h = N.instagram_handle(d["instagram_url"] or "")
        if d["instagram_url"] and not h:
            raise ValidationError("That doesn't look like an Instagram profile URL or @handle")
        out["instagram_handle"] = h
        out["instagram_url"] = N.instagram_url(h)
    if "tiktok_url" in d:
        h = N.tiktok_handle(d["tiktok_url"] or "")
        if d["tiktok_url"] and not h:
            raise ValidationError("That doesn't look like a TikTok profile URL or @handle")
        out["tiktok_handle"] = h
        out["tiktok_url"] = N.tiktok_url(h)

    if "website_url" in d:
        url = N.clean_url(d["website_url"] or "")
        kind = N.classify_url(url) if url else ""
        if kind == "instagram" and not out.get("instagram_handle"):
            out["instagram_handle"] = N.instagram_handle(url)
            out["instagram_url"] = N.instagram_url(out["instagram_handle"])
            url = ""
        elif kind == "tiktok" and not out.get("tiktok_handle"):
            out["tiktok_handle"] = N.tiktok_handle(url)
            out["tiktok_url"] = N.tiktok_url(out["tiktok_handle"])
            url = ""
        elif kind in ("link_page", "whatsapp", "shortener", "storefront") and not d.get("link_in_bio_url"):
            d["link_in_bio_url"] = url  # a link page is not the business's own website
            url = ""
        elif url and not url.startswith(("http://", "https://")):
            raise ValidationError("Website must be a URL like https://example.com")
        out["website_url"] = url
        out["website_domain"] = N.business_domain(url)
        prev = (existing or {}).get("website_url") or ""
        if url and url != prev:
            out.update(website_status="has_website", website_quality=None, website_quality_notes="[]",
                       website_evidence="", website_suggestion="")
        elif not url and prev:
            out.update(website_status="unknown", website_quality=None, website_quality_notes="[]", website_evidence="")
    if d.get("no_website_confirmed") and not out.get("website_url") and not (existing or {}).get("website_url"):
        out.update(website_status="none_found", website_url="", website_domain="",
                   website_evidence=f"Confirmed manually on {N.today().isoformat()}: no website")

    if "link_in_bio_url" in d:
        url = N.clean_url(d["link_in_bio_url"] or "")
        out["link_in_bio_url"] = url
        out["link_in_bio_type"] = N.link_in_bio_type(url) if url else "unknown"
    if d.get("no_link_in_bio"):
        out["link_in_bio_url"] = ""
        out["link_in_bio_type"] = "none"

    if "whatsapp" in d:
        wa = N.whatsapp_from_url(d["whatsapp"] or "") or N.phone_key(d["whatsapp"] or "")
        out["whatsapp"] = N.pretty_phone(wa)
    if "phone" in d:
        out["phone"] = N.pretty_phone(N.phone_key(d["phone"] or ""))
    if "whatsapp" in d or "phone" in d:
        wa = out.get("whatsapp", (existing or {}).get("whatsapp", ""))
        ph = out.get("phone", (existing or {}).get("phone", ""))
        out["phone_key"] = N.phone_key(ph or wa)
    if "email" in d:
        e = N.clean_email(d["email"] or "")
        if d["email"] and not e:
            raise ValidationError("Email address is not valid")
        out["email"] = e

    for f in ("city", "state", "country", "subcategory", "founder_name", "address", "followers_source"):
        if f in d:
            out[f] = N.clean_text(d[f], 160)
    if "city" in out and out["city"]:
        out["city"] = " ".join(w.capitalize() if w.islower() else w for w in out["city"].split())
        st = N.state_for_city(out["city"])
        if st and not (out.get("state") or (existing or {}).get("state")):
            out["state"] = st
        if st and not (out.get("country") or (existing or {}).get("country")):
            out["country"] = "Nigeria"
    if "industry" in d:
        ind = match_industry(settings, d["industry"] or "")
        out["industry"] = ind["name"] if ind else N.clean_text(d["industry"], 80)
    if "notes" in d:
        out["notes"] = N.clean_text(d["notes"], 20000)
    if "profile_bio" in d:
        out["profile_bio"] = N.clean_text(d["profile_bio"], 2000)
    for f in ("followers_instagram", "followers_tiktok"):
        if f in d:
            out[f] = _int_or_none(d[f])
    if "other_socials" in d:
        v = d["other_socials"]
        if isinstance(v, str):
            v = loads(v, {}) or {}
        out["other_socials"] = dumps({k: N.clean_url(u) for k, u in (v or {}).items() if u})
    if "status" in d:
        if d["status"] not in STATUSES:
            raise ValidationError(f"Unknown status: {d['status']}")
        out["status"] = d["status"]
    if "follow_up_at" in d:
        fd = N.to_date(d["follow_up_at"]) if d["follow_up_at"] else None
        if d["follow_up_at"] and not fd:
            raise ValidationError("Follow-up date is not valid")
        out["follow_up_at"] = fd.isoformat() if fd else None

    name = out.get("business_name", (existing or {}).get("business_name", ""))
    if not name:
        handle = out.get("instagram_handle") or out.get("tiktok_handle") or (out.get("website_domain") or "").split(".")[0]
        if handle:
            name = N.title_case_handle(handle)
            out["business_name"] = name
    if "business_name" in out or existing is None:
        if not name:
            raise ValidationError("Business name (or an Instagram / TikTok / website) is required")
        out["name_key"] = N.name_key(name)
    return out


def create(conn: Conn, data: dict, settings: dict, source: str = "manual", force: bool = False) -> int:
    fields = prepare(data, settings)
    if not force:
        dups = find_duplicates(conn, fields)
        if dups:
            raise DuplicateError(dups)
    ts = N.now_iso()
    row = {"status": "New", "source": source, "discovered_at": ts, "created_at": ts, "updated_at": ts,
           "website_status": "unknown", **fields}
    if row.get("website_url") and row.get("website_status") == "unknown":
        row["website_status"] = "has_website"
    lead_id = conn.insert("leads", row)
    conn.run("INSERT INTO outcomes (lead_id, updated_at) VALUES (?, ?)", [lead_id, ts])
    log(conn, lead_id, "created", detail=f"Added via {source}")
    return lead_id


def update(conn: Conn, lead_id: int, data: dict, settings: dict) -> dict:
    existing = conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])
    if not existing:
        raise KeyError(lead_id)
    fields = prepare(data, settings, existing)
    if any(k in fields for k in ("instagram_handle", "tiktok_handle", "website_domain", "phone_key", "email", "name_key")):
        probe = {**existing, **fields}
        strong = [m for m in find_duplicates(conn, probe, exclude_id=lead_id) if m["strength"] == "strong"]
        if strong and not data.get("force"):
            raise DuplicateError(strong)
    new_status = fields.pop("status", None)
    fields["updated_at"] = N.now_iso()
    conn.update("leads", lead_id, fields)
    if new_status and new_status != existing["status"]:
        set_status(conn, lead_id, new_status)
    return conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])


def log(conn: Conn, lead_id: int, type_: str, detail: str = "", channel: str = "", from_status: str = "", to_status: str = ""):
    conn.insert("activities", {"lead_id": lead_id, "type": type_, "detail": N.clean_text(detail, 4000), "channel": channel,
                               "from_status": from_status, "to_status": to_status, "created_at": N.now_iso()})


def set_status(conn: Conn, lead_id: int, status: str, detail: str = "") -> None:
    if status not in STATUSES:
        raise ValidationError(f"Unknown status: {status}")
    lead = conn.one("SELECT status, opportunity_score, kard_fit, business_quality, score_breakdown, contacted_at FROM leads WHERE id = ?", [lead_id])
    if not lead:
        raise KeyError(lead_id)
    ts = N.now_iso()
    conn.update("leads", lead_id, {"status": status, "updated_at": ts})
    log(conn, lead_id, "status", detail=detail, from_status=lead["status"], to_status=status)
    flags = STATUS_OUTCOME.get(status, [])
    if flags:
        _set_outcome_flags(conn, lead_id, flags, lead)
    if status in ("Contacted", "Replied", "Interested", "Call/Meeting", "Proposal", "Won") and not lead["contacted_at"]:
        conn.update("leads", lead_id, {"contacted_at": ts})


def _set_outcome_flags(conn: Conn, lead_id: int, flags: list[str], lead: dict) -> None:
    ts = N.now_iso()
    out = conn.one("SELECT * FROM outcomes WHERE lead_id = ?", [lead_id])
    if not out:
        conn.run("INSERT INTO outcomes (lead_id, updated_at) VALUES (?, ?)", [lead_id, ts])
        out = conn.one("SELECT * FROM outcomes WHERE lead_id = ?", [lead_id])
    upd = {f: 1 for f in flags}
    if "contacted" in flags and not out["first_contacted_at"]:
        bd = loads(lead.get("score_breakdown"), {}) or {}
        features = {c["key"]: c["raw"] for c in bd.get("categories", [])}
        features["signals"] = sorted({i["code"] for c in bd.get("categories", []) for i in c["items"] if i["points"] > 0})
        features["confidence"] = (bd.get("confidence") or {}).get("level")
        upd.update(first_contacted_at=ts, score_at_contact=lead.get("opportunity_score"),
                   fit_at_contact=lead.get("kard_fit"), quality_at_contact=lead.get("business_quality"),
                   features_at_contact=dumps(features))
    if "responded" in flags and not out["responded_at"]:
        upd["responded_at"] = ts
    if "purchased" in flags and not out["won_at"]:
        upd["won_at"] = ts
    upd["updated_at"] = ts
    conn.update("outcomes", lead_id, upd, key="lead_id")


def mark_contacted(conn: Conn, lead_id: int, channel: str, note: str = "", follow_up_days: int | None = None) -> None:
    lead = conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])
    if not lead:
        raise KeyError(lead_id)
    if channel not in CHANNELS:
        raise ValidationError("Unknown channel")
    ts = N.now_iso()
    upd = {"contacted_at": ts, "last_contact_channel": channel, "updated_at": ts}
    if follow_up_days:
        upd["follow_up_at"] = (N.today() + timedelta(days=int(follow_up_days))).isoformat()
    conn.update("leads", lead_id, upd)
    log(conn, lead_id, "contacted", detail=note or f"Contacted via {channel}", channel=channel)
    if lead["status"] in ("New", "Researching", "Qualified", "Follow-up", "Contacted"):
        if lead["status"] != "Contacted":
            set_status(conn, lead_id, "Contacted")
        else:
            _set_outcome_flags(conn, lead_id, ["contacted"], lead)
    else:
        _set_outcome_flags(conn, lead_id, ["contacted"], lead)


def set_follow_up(conn: Conn, lead_id: int, date_str: str | None, note: str = "") -> None:
    d = N.to_date(date_str) if date_str else None
    if date_str and not d:
        raise ValidationError("Follow-up date is not valid")
    conn.update("leads", lead_id, {"follow_up_at": d.isoformat() if d else None, "updated_at": N.now_iso()})
    log(conn, lead_id, "follow_up", detail=(f"Follow-up set for {d.isoformat()}" if d else "Follow-up cleared") + (f" — {note}" if note else ""))


def update_outcome(conn: Conn, lead_id: int, data: dict) -> dict:
    allowed = {"revenue", "currency", "package"}
    upd = {}
    for k in allowed & set(data):
        if k == "revenue":
            v = data[k]
            if v in (None, ""):
                upd[k] = None
            else:
                try:
                    upd[k] = float(v)
                except (TypeError, ValueError):
                    raise ValidationError("Revenue must be a number")
                if upd[k] < 0:
                    raise ValidationError("Revenue cannot be negative")
        else:
            upd[k] = N.clean_text(data[k], 60)
    if upd:
        upd["updated_at"] = N.now_iso()
        conn.update("outcomes", lead_id, upd, key="lead_id")
        log(conn, lead_id, "outcome", detail="Outcome updated: " + ", ".join(f"{k}={v}" for k, v in upd.items() if k != "updated_at"))
    return conn.one("SELECT * FROM outcomes WHERE lead_id = ?", [lead_id])


# --------------------------------------------------------------------------- reads

def decode(lead: dict) -> dict:
    lead = dict(lead)
    lead["other_socials"] = loads(lead.get("other_socials"), {}) or {}
    lead["website_quality_notes"] = loads(lead.get("website_quality_notes"), []) or []
    lead["score_breakdown"] = loads(lead.get("score_breakdown"), {}) or {}
    lead["ai_pain_points"] = loads(lead.get("ai_pain_points"), []) or []
    return lead


def observations(conn: Conn, lead_id: int) -> list[dict]:
    rows = conn.all("SELECT * FROM observations WHERE lead_id = ? ORDER BY COALESCE(observed_at, collected_at) DESC, id DESC", [lead_id])
    for r in rows:
        r["meta"] = loads(r.get("meta"), {}) or {}
    return rows


def signal_rows(conn: Conn, lead_id: int) -> list[dict]:
    rows = conn.all("SELECT * FROM signals WHERE lead_id = ? ORDER BY id", [lead_id])
    for r in rows:
        r["evidence"] = loads(r.get("evidence"), []) or []
    return rows


def get_full(conn: Conn, lead_id: int) -> dict | None:
    lead = conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])
    if not lead:
        return None
    lead = decode(lead)
    lead["observations"] = observations(conn, lead_id)
    lead["signals"] = signal_rows(conn, lead_id)
    lead["outreach"] = conn.all("SELECT * FROM outreach_messages WHERE lead_id = ? ORDER BY generator DESC, id", [lead_id])
    for m in lead["outreach"]:
        m["grounding"] = loads(m.get("grounding"), []) or []
    lead["activities"] = conn.all("SELECT * FROM activities WHERE lead_id = ? ORDER BY id DESC LIMIT 200", [lead_id])
    lead["outcome"] = conn.one("SELECT * FROM outcomes WHERE lead_id = ?", [lead_id])
    lead["history"] = conn.all("SELECT opportunity_score, kard_fit, business_quality, confidence, created_at FROM score_snapshots "
                               "WHERE lead_id = ? ORDER BY id DESC LIMIT 12", [lead_id])
    lead["ai_runs"] = conn.all("SELECT id, model, status, input_tokens, output_tokens, est_cost_usd, error, dropped, created_at "
                               "FROM ai_runs WHERE lead_id = ? ORDER BY id DESC LIMIT 5", [lead_id])
    return lead


LIST_COLUMNS = ("id, business_name, industry, subcategory, city, state, country, instagram_url, instagram_handle, tiktok_url, "
                "tiktok_handle, website_url, website_domain, website_status, link_in_bio_type, whatsapp, phone, email, "
                "followers_instagram, followers_tiktok, status, source, discovered_at, contacted_at, follow_up_at, "
                "opportunity_score, kard_fit, business_quality, confidence, fit_points, social_points, gap_points, "
                "buying_points, access_points, buying_signal_count, latest_buying_signal_at, latest_buying_signal, "
                "top_reason, top_pain, pitch_angle, last_researched_at, last_analyzed_at, last_scored_at, ai_model")

SORTS = {
    "opportunity": "(opportunity_score IS NULL), opportunity_score DESC, kard_fit DESC, id DESC",
    "fit": "(kard_fit IS NULL), kard_fit DESC, opportunity_score DESC, id DESC",
    "quality": "(business_quality IS NULL), business_quality DESC, id DESC",
    "discovered": "discovered_at DESC, id DESC",
    "name": "business_name ASC, id ASC",
    "buying": "(latest_buying_signal_at IS NULL), latest_buying_signal_at DESC, opportunity_score DESC",
    "followup": "(follow_up_at IS NULL), follow_up_at ASC, id DESC",
    "updated": "updated_at DESC, id DESC",
}


def _truthy(v) -> bool | None:
    if v in (None, "", "any"):
        return None
    return str(v).lower() in ("1", "true", "yes", "y")


def build_filters(f: dict, settings: dict) -> tuple[str, list]:
    where, params = ["archived = 0"], []

    def num(key):
        v = f.get(key)
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValidationError(f"Filter {key} must be a number")

    q = N.clean_text(f.get("q"), 100).lower()
    if q:
        like = f"%{q.lstrip('@')}%"
        where.append("(lower(business_name) LIKE ? OR instagram_handle LIKE ? OR tiktok_handle LIKE ? OR website_domain LIKE ? "
                     "OR lower(city) LIKE ? OR lower(notes) LIKE ?)")
        params += [like] * 6
    for key, col in (("city", "city"), ("industry", "industry"), ("status", "status"), ("confidence", "confidence"),
                     ("source", "source")):
        v = f.get(key)
        if v:
            vals = [x.strip() for x in str(v).split(",") if x.strip()]
            if vals:
                where.append(f"lower({col}) IN ({', '.join('?' for _ in vals)})")
                params += [x.lower() for x in vals]
    for key, col, op in (("min_score", "opportunity_score", ">="), ("max_score", "opportunity_score", "<="),
                         ("min_fit", "kard_fit", ">="), ("max_fit", "kard_fit", "<="),
                         ("min_quality", "business_quality", ">="), ("max_quality", "business_quality", "<=")):
        v = num(key)
        if v is not None:
            where.append(f"{col} {op} ?")
            params.append(v)
    w = settings["weights"]
    for key, col, cat in (("min_social_pct", "social_points", "social_activity"), ("min_gap_pct", "gap_points", "digital_gap"),
                          ("min_buying_pct", "buying_points", "buying_signals"), ("min_access_pct", "access_points", "accessibility")):
        v = num(key)
        if v is not None:
            where.append(f"{col} >= ?")
            params.append(w[cat] * v / 100.0)
    tri = {
        "has_buying": ("buying_signal_count > 0", "(buying_signal_count = 0 OR buying_signal_count IS NULL)"),
        "has_website": ("website_status = 'has_website'", "website_status IN ('none_found', 'parked', 'unreachable')"),
        "has_instagram": ("instagram_handle <> ''", "(instagram_handle = '' OR instagram_handle IS NULL)"),
        "has_tiktok": ("tiktok_handle <> ''", "(tiktok_handle = '' OR tiktok_handle IS NULL)"),
        "has_whatsapp": ("(whatsapp <> '' OR phone <> '')", "((whatsapp = '' OR whatsapp IS NULL) AND (phone = '' OR phone IS NULL))"),
        "has_email": ("email <> ''", "(email = '' OR email IS NULL)"),
        "contacted": ("contacted_at IS NOT NULL", "contacted_at IS NULL"),
        "scored": ("opportunity_score IS NOT NULL", "opportunity_score IS NULL"),
    }
    for key, (yes_sql, no_sql) in tri.items():
        t = _truthy(f.get(key))
        if t is True:
            where.append(yes_sql)
        elif t is False:
            where.append(no_sql)
    if f.get("website_unknown") in ("1", 1, True, "true"):
        where.append("website_status = 'unknown'")
    if _truthy(f.get("followup_due")):
        where.append("follow_up_at IS NOT NULL AND follow_up_at <= ? AND status NOT IN ('Won', 'Lost', 'Not a fit')")
        params.append(N.today().isoformat())
    rd = num("recent_days")
    if rd:
        where.append("discovered_at >= ?")
        params.append((N.today() - timedelta(days=int(rd))).isoformat())
    bd = num("buying_recent_days")
    if bd:
        where.append("latest_buying_signal_at >= ?")
        params.append((N.today() - timedelta(days=int(bd))).isoformat())
    return " AND ".join(where), params


def list_leads(conn: Conn, f: dict, settings: dict) -> dict:
    where, params = build_filters(f, settings)
    order = SORTS.get(f.get("sort") or "opportunity", SORTS["opportunity"])
    try:
        per_page = max(1, min(200, int(f.get("per_page") or 50)))
        page = max(1, int(f.get("page") or 1))
    except ValueError:
        raise ValidationError("page / per_page must be numbers")
    total = conn.scalar(f"SELECT COUNT(*) AS n FROM leads WHERE {where}", params) or 0
    rows = conn.all(f"SELECT {LIST_COLUMNS} FROM leads WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                    [*params, per_page, (page - 1) * per_page])
    return {"total": total, "page": page, "per_page": per_page, "leads": rows}


def archive(conn: Conn, lead_id: int) -> None:
    conn.update("leads", lead_id, {"archived": 1, "updated_at": N.now_iso()})
    log(conn, lead_id, "archived", detail="Lead archived (kept for outcome history)")
