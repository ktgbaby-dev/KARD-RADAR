"""CSV import / export. Exported files re-import cleanly (round trip); duplicates are merged, not re-created."""
import csv
import io
import re

from . import leads as L
from .db import Conn, loads
from .dedupe import find_duplicates

EXPORT_COLUMNS = [
    ("id", "id"), ("business_name", "business_name"), ("industry", "industry"), ("subcategory", "subcategory"),
    ("city", "city"), ("state", "state"), ("country", "country"), ("instagram_url", "instagram_url"),
    ("tiktok_url", "tiktok_url"), ("website_url", "website_url"), ("website_status", "website_status"),
    ("link_in_bio_url", "link_in_bio_url"), ("whatsapp", "whatsapp"), ("phone", "phone"), ("email", "email"),
    ("founder_name", "founder_name"), ("followers_instagram", "followers_instagram"),
    ("followers_tiktok", "followers_tiktok"), ("opportunity_score", "opportunity_score"), ("kard_fit", "kard_fit"),
    ("business_quality", "business_quality"), ("confidence", "confidence"), ("top_reason", "top_reason"),
    ("top_pain", "top_pain"), ("latest_buying_signal", "latest_buying_signal"),
    ("latest_buying_signal_at", "latest_buying_signal_at"), ("pitch_angle", "pitch_angle"), ("status", "status"),
    ("discovered_at", "discovered_at"), ("contacted_at", "contacted_at"), ("follow_up_at", "follow_up_at"),
    ("notes", "notes"),
]

ALIASES = {
    "business name": "business_name", "business": "business_name", "name": "business_name", "brand": "business_name",
    "brand name": "business_name", "company": "business_name",
    "industry": "industry", "category": "industry", "niche": "industry", "sector": "industry",
    "subcategory": "subcategory", "sub category": "subcategory",
    "city": "city", "location": "city", "town": "city", "state": "state", "country": "country",
    "instagram": "instagram_url", "instagram url": "instagram_url", "ig": "instagram_url", "instagram handle": "instagram_url",
    "tiktok": "tiktok_url", "tiktok url": "tiktok_url", "tiktok handle": "tiktok_url",
    "website": "website_url", "website url": "website_url", "site": "website_url", "url": "website_url", "web": "website_url",
    "link in bio": "link_in_bio_url", "link in bio url": "link_in_bio_url", "bio link": "link_in_bio_url",
    "whatsapp": "whatsapp", "whatsapp number": "whatsapp", "phone": "phone", "phone number": "phone", "telephone": "phone",
    "mobile": "phone", "email": "email", "email address": "email", "e mail": "email",
    "founder": "founder_name", "founder name": "founder_name", "owner": "founder_name", "contact person": "founder_name",
    "followers": "followers_instagram", "instagram followers": "followers_instagram", "followers instagram": "followers_instagram",
    "tiktok followers": "followers_tiktok", "followers tiktok": "followers_tiktok",
    "bio": "profile_bio", "profile bio": "profile_bio", "address": "address",
    "notes": "notes", "note": "notes", "comments": "notes", "status": "status", "follow up at": "follow_up_at",
    "follow up": "follow_up_at", "follow up date": "follow_up_at",
}
IMPORTABLE = {"business_name", "industry", "subcategory", "city", "state", "country", "instagram_url", "tiktok_url",
              "website_url", "link_in_bio_url", "whatsapp", "phone", "email", "founder_name", "followers_instagram",
              "followers_tiktok", "profile_bio", "address", "notes", "status", "follow_up_at"}
MAX_ROWS = 5000
_SAFE_NUMBER = re.compile(r"^[+-]?\d[\d\s().-]*$")


def _safe_cell(v) -> str:
    """Neutralise spreadsheet formula injection while keeping phone numbers readable."""
    s = "" if v is None else str(v)
    if s and (s[0] in "=@\t\r" or (s[0] in "+-" and not _SAFE_NUMBER.match(s))):
        return "'" + s
    return s


def export_csv(conn: Conn, filters: dict, settings: dict) -> str:
    where, params = L.build_filters(filters, settings)
    order = L.SORTS.get(filters.get("sort") or "opportunity", L.SORTS["opportunity"])
    cols = ", ".join(c for c, _ in EXPORT_COLUMNS)
    rows = conn.all(f"SELECT {cols} FROM leads WHERE {where} ORDER BY {order}", params)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([h for _, h in EXPORT_COLUMNS])
    for r in rows:
        w.writerow([_safe_cell(r[c]) for c, _ in EXPORT_COLUMNS])
    return "﻿" + buf.getvalue()  # BOM so Excel opens UTF-8 (₦, emoji) correctly


def _header_key(h: str) -> str:
    k = re.sub(r"[_\-]+", " ", (h or "").strip().lower().lstrip("﻿"))
    k = re.sub(r"\s+", " ", k)
    if k in ALIASES:
        return ALIASES[k]
    k2 = k.replace(" ", "_")
    return k2 if k2 in IMPORTABLE else ""


def import_csv(conn: Conn, text: str, settings: dict) -> dict:
    text = (text or "").lstrip("﻿")
    if not text.strip():
        raise L.ValidationError("The CSV file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        headers = next(reader)
    except StopIteration:
        raise L.ValidationError("The CSV file has no header row")
    mapping = [_header_key(h) for h in headers]
    if not any(m in ("business_name", "instagram_url", "tiktok_url", "website_url") for m in mapping):
        raise L.ValidationError("Need at least one of these columns: business name, instagram, tiktok, website")
    report = {"created": [], "merged": [], "skipped": [], "errors": [], "columns": {h: m or None for h, m in zip(headers, mapping)}}
    for n, row in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            report["errors"].append({"row": n, "error": f"Stopped after {MAX_ROWS} rows"})
            break
        if not any(c.strip() for c in row):
            continue
        data = {}
        for m, v in zip(mapping, row):
            if not m:
                continue
            v = v.strip()
            if v.startswith("'") and len(v) > 1 and v[1] in "=+-@":
                v = v[1:]
            if v:
                data[m] = v
        if "status" in data and data["status"] not in L.STATUSES:
            data.pop("status")
        try:
            probe = L.prepare(data, settings)
            dups = find_duplicates(conn, probe)
            strong = [d for d in dups if d["strength"] == "strong"]
            if strong:
                existing = conn.one("SELECT * FROM leads WHERE id = ?", [strong[0]["lead_id"]])
                column = {"instagram_url": "instagram_handle", "tiktok_url": "tiktok_handle"}
                upd = {k: v for k, v in data.items() if k not in ("status",)
                       and existing.get(column.get(k, k)) in (None, "", "{}")}
                if upd:
                    try:
                        L.update(conn, existing["id"], upd, settings)
                    except L.DuplicateError:
                        upd = {}
                report["merged"].append({"row": n, "lead_id": existing["id"], "business_name": existing["business_name"],
                                         "match_on": strong[0]["match_on"], "fields_filled": sorted(upd)})
            elif dups:
                report["skipped"].append({"row": n, "business_name": probe.get("business_name"), "lead_id": dups[0]["lead_id"],
                                          "reason": "Possible duplicate of “" + dups[0]["business_name"] + "” (same name + city)"})
            else:
                status = data.pop("status", None)
                lead_id = L.create(conn, data, settings, source="csv", force=True)
                if status and status != "New":
                    L.set_status(conn, lead_id, status, detail="Status from CSV import")
                report["created"].append({"row": n, "lead_id": lead_id, "business_name": probe.get("business_name")})
        except L.ValidationError as e:
            report["errors"].append({"row": n, "error": str(e)})
    return report


def export_learning_csv(conn: Conn) -> str:
    """Outcome dataset for future conversion analysis: features at contact time + funnel outcome."""
    rows = conn.all("SELECT l.id, l.industry, l.city, l.opportunity_score, l.kard_fit, l.business_quality, l.confidence, "
                    "o.contacted, o.responded, o.interested, o.meeting, o.proposal, o.purchased, o.lost, o.revenue, o.currency, "
                    "o.score_at_contact, o.fit_at_contact, o.quality_at_contact, o.features_at_contact, o.first_contacted_at, o.won_at "
                    "FROM leads l JOIN outcomes o ON o.lead_id = l.id WHERE o.contacted = 1 ORDER BY l.id")
    cats = ["business_fit", "social_activity", "digital_gap", "buying_signals", "accessibility"]
    buf = io.StringIO()
    w = csv.writer(buf)
    head = ["lead_id", "industry", "city", "score_at_contact", "fit_at_contact", "quality_at_contact", *[f"raw_{c}" for c in cats],
            "signals_at_contact", "confidence_at_contact", "current_score", "responded", "interested", "meeting", "proposal",
            "purchased", "lost", "revenue", "currency", "first_contacted_at", "won_at"]
    w.writerow(head)
    for r in rows:
        f = loads(r["features_at_contact"], {}) or {}
        w.writerow([r["id"], r["industry"], r["city"], r["score_at_contact"], r["fit_at_contact"], r["quality_at_contact"],
                    *[f.get(c, "") for c in cats], " ".join(f.get("signals", [])), f.get("confidence", ""),
                    r["opportunity_score"], r["responded"], r["interested"], r["meeting"], r["proposal"], r["purchased"],
                    r["lost"], r["revenue"] if r["revenue"] is not None else "", r["currency"], r["first_contacted_at"] or "",
                    r["won_at"] or ""])
    return "﻿" + buf.getvalue()
