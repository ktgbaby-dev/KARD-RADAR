"""Duplicate detection. Strong keys (domain, handles, phone, email) identify a business outright;
a normalized-name match counts only when no strong key conflicts and the cities agree."""
from .db import Conn

STRONG_KEYS = [("instagram_handle", "Instagram"), ("tiktok_handle", "TikTok"), ("website_domain", "website domain"),
               ("phone_key", "phone"), ("email", "email")]


def find_duplicates(conn: Conn, lead: dict, exclude_id: int | None = None) -> list[dict]:
    clauses, params = [], []
    for key, _ in STRONG_KEYS:
        if lead.get(key):
            clauses.append(f"{key} = ?")
            params.append(lead[key])
    if lead.get("name_key") and len(lead["name_key"]) >= 3:
        clauses.append("name_key = ?")
        params.append(lead["name_key"])
    if not clauses:
        return []
    sql = ("SELECT id, business_name, name_key, city, instagram_handle, tiktok_handle, website_domain, phone_key, email, status "
           f"FROM leads WHERE archived = 0 AND ({' OR '.join(clauses)})")
    if exclude_id:
        sql += " AND id <> ?"
        params.append(exclude_id)
    matches = []
    for row in conn.all(sql, params):
        strong = [label for key, label in STRONG_KEYS if lead.get(key) and row.get(key) == lead[key]]
        if strong:
            matches.append({"lead_id": row["id"], "business_name": row["business_name"], "strength": "strong",
                            "match_on": strong, "status": row["status"]})
            continue
        if lead.get("name_key") and row["name_key"] == lead["name_key"]:
            conflict = [label for key, label in STRONG_KEYS
                        if lead.get(key) and row.get(key) and row[key] != lead[key]]
            city_a, city_b = (lead.get("city") or "").strip().lower(), (row.get("city") or "").strip().lower()
            if conflict or (city_a and city_b and city_a != city_b):
                continue
            matches.append({"lead_id": row["id"], "business_name": row["business_name"], "strength": "probable",
                            "match_on": ["business name" + (" + city" if city_a and city_b else "")], "status": row["status"]})
    matches.sort(key=lambda m: 0 if m["strength"] == "strong" else 1)
    return matches


MERGE_FIELDS = ["industry", "subcategory", "city", "state", "country", "instagram_url", "instagram_handle", "tiktok_url",
                "tiktok_handle", "website_url", "website_domain", "link_in_bio_url", "whatsapp", "phone", "phone_key", "email",
                "founder_name", "followers_instagram", "followers_tiktok", "followers_source", "profile_bio", "address"]


def merge_fields(existing: dict, incoming: dict) -> dict:
    """Fields to update on `existing`: fill blanks only; never overwrite data already on the record."""
    updates = {}
    for f in MERGE_FIELDS:
        new = incoming.get(f)
        if new in (None, "") or existing.get(f) not in (None, ""):
            continue
        updates[f] = new
    if incoming.get("notes"):
        joined = (existing.get("notes") or "").strip()
        if incoming["notes"].strip() not in joined:
            updates["notes"] = (joined + "\n" + incoming["notes"].strip()).strip()
    return updates
