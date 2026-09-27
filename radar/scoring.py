"""Deterministic Kard scoring. Pure function of (lead, resolved signals, observations, settings).

The AI never sets a score. It can only propose signals (with cited evidence), which are resolved alongside
rule signals before this module runs. Every point awarded is traceable to a line item with a reason.
"""
import json
from datetime import date

from . import normalize as N
from .signals import BUYING_CODES, CATALOG, FRICTION_CODES

CATEGORIES = [
    ("business_fit", "Business fit", 20, ["nigerian_business", "target_industry", "sells_offering", "customer_facing"]),
    ("social_activity", "Social activity", 20, ["posted_recently", "consistent_posting", "active_social_presence", "audience_engagement"]),
    ("digital_gap", "Digital presence gap", 30, ["no_website", "weak_website", "no_landing_page", "weak_link_in_bio", "info_hard_to_find"]),
    ("buying_signals", "Buying / marketing signals", 20, BUYING_CODES),
    ("accessibility", "Accessibility", 10, ["has_instagram", "has_tiktok", "has_whatsapp", "has_email", "decision_maker"]),
]
UNDATED_BUYING_POINTS = 3


def _item(code, sig, points, state=None, note=""):
    meta = CATALOG[code]
    return {
        "code": code, "label": meta["label"], "max": meta["points"], "points": points,
        "state": state or (sig or {}).get("state", "unknown"),
        "detector": (sig or {}).get("detector", "rule"),
        "detail": (sig or {}).get("detail", ""),
        "evidence": (sig or {}).get("evidence", []),
        "date": (sig or {}).get("signal_date"),
        "note": note,
    }


def score(lead: dict, signals: dict[str, dict], observations: list[dict], settings: dict,
          ref: date | None = None) -> dict:
    ref = ref or N.today()
    weights = settings["weights"]
    window = int(settings["buying_signal_window_days"])
    cats = []
    raw = {}
    for key, label, cap, codes in CATEGORIES:
        items = []
        if key == "buying_signals":
            for code in codes:
                sig = signals.get(code)
                if not sig or sig.get("state") != "yes":
                    continue
                d = N.to_date(sig.get("signal_date"))
                if d is None:
                    items.append(_item(code, sig, UNDATED_BUYING_POINTS, "yes", "Date unknown — partial credit"))
                elif (ref - d).days <= window:
                    age = (ref - d).days
                    items.append(_item(code, sig, CATALOG[code]["points"], "yes", f"{age} day(s) ago"))
                else:
                    items.append(_item(code, sig, 0, "stale", f"Older than the {window}-day window ({d.isoformat()})"))
            items.sort(key=lambda i: -i["points"])
            if not items:
                items.append({"code": "none", "label": "No buying signals found in the evidence", "max": 0, "points": 0,
                              "state": "unknown", "detector": "rule", "detail": "Add recent posts or run discovery to find campaigns, launches or events",
                              "evidence": [], "date": None, "note": ""})
        else:
            for code in codes:
                sig = signals.get(code)
                pts = CATALOG[code]["points"] if sig and sig.get("state") == "yes" else 0
                items.append(_item(code, sig, pts))
        got = min(cap, sum(i["points"] for i in items))
        raw[key] = got
        weight = int(weights.get(key, cap))
        cats.append({"key": key, "label": label, "cap": cap, "raw": got, "weight": weight,
                     "points": round(got / cap * weight, 1) if cap else 0, "items": items,
                     "capped": sum(i["points"] for i in items) > cap})

    opportunity = int(round(sum(c["points"] for c in cats)))

    # ---- Kard Fit: need for a central customer touchpoint
    friction = [c for c in FRICTION_CODES if signals.get(c, {}).get("state") == "yes"]
    friction_pct = min(len(friction), 3) / 3
    fit_components = [
        {"label": "Digital presence gap", "max": 60, "points": round(raw["digital_gap"] / 30 * 60, 1),
         "detail": f"{raw['digital_gap']}/30 gap points"},
        {"label": "Business fit", "max": 25, "points": round(raw["business_fit"] / 20 * 25, 1),
         "detail": f"{raw['business_fit']}/20 fit points"},
        {"label": "Customer-journey friction", "max": 15, "points": round(friction_pct * 15, 1),
         "detail": (", ".join(CATALOG[c]["label"] for c in friction)) or "None observed"},
    ]
    kard_fit = int(round(sum(c["points"] for c in fit_components)))

    # ---- Business Quality: how established / professional / active
    def yes(code):
        return signals.get(code, {}).get("state") == "yes"
    brand_pts, brand_bits = 0, []
    if yes("strong_visual_branding"):
        brand_pts += 10
        brand_bits.append("strong visual branding")
    if yes("professional_bio"):
        brand_pts += 5
        brand_bits.append("clear bio")
    other = lead.get("other_socials") or {}
    if isinstance(other, str):
        try:
            other = json.loads(other or "{}")
        except ValueError:
            other = {}
    presence = sum([bool(lead.get("instagram_handle")), bool(lead.get("tiktok_handle")),
                    lead.get("website_status") == "has_website", *[bool(v) for v in other.values()]])
    if presence >= 2:
        brand_pts += 5
        brand_bits.append(f"{presence} channels")
    wq = lead.get("website_quality")
    if lead.get("website_status") == "has_website" and wq is not None and wq >= 70:
        brand_pts += 5
        brand_bits.append(f"good website ({wq}/100)")

    followers = max(lead.get("followers_instagram") or 0, lead.get("followers_tiktok") or 0)
    if lead.get("followers_instagram") is None and lead.get("followers_tiktok") is None:
        aud_pts, aud_detail = 0, "Unknown — follower count not recorded (supporting signal only)"
    else:
        bands = [(100_000, 15), (20_000, 13), (5_000, 10), (1_000, 7), (300, 4), (0, 1)]
        aud_pts = next(p for t, p in bands if followers >= t)
        aud_detail = f"{followers:,} followers ({lead.get('followers_source') or 'source not recorded'}) — supporting signal only"

    contact_pts, contact_bits = 0, []
    if lead.get("whatsapp") or lead.get("phone"):
        contact_pts += 4
        contact_bits.append("phone/WhatsApp")
    if lead.get("email"):
        contact_pts += 3
        contact_bits.append("email")
    if lead.get("address") or yes("location_in_captions"):
        contact_pts += 3
        contact_bits.append("location")
    quality_components = [
        {"label": "Social activity", "max": 35, "points": round(raw["social_activity"] / 20 * 35, 1),
         "detail": f"{raw['social_activity']}/20 activity points"},
        {"label": "Brand & presentation", "max": 25, "points": brand_pts,
         "detail": ", ".join(brand_bits) or "No brand-quality indicators recorded yet"},
        {"label": "Audience size", "max": 15, "points": aud_pts, "detail": aud_detail},
        {"label": "Marketing activity", "max": 15, "points": round(raw["buying_signals"] / 20 * 15, 1),
         "detail": f"{raw['buying_signals']}/20 buying-signal points"},
        {"label": "Contactability", "max": 10, "points": contact_pts,
         "detail": ", ".join(contact_bits) or "No published contact details on record"},
    ]
    business_quality = int(round(sum(c["points"] for c in quality_components)))

    confidence = assess_confidence(lead, signals, observations, cats, settings, ref)

    # ---- explanations
    scored_items = [i for c in cats for i in c["items"] if i["points"] > 0]
    cat_rank = {"digital_gap": 0, "buying_signals": 1, "social_activity": 2, "business_fit": 3, "accessibility": 4}
    rank = {i["code"]: cat_rank[c["key"]] for c in cats for i in c["items"]}
    why = []
    for i in sorted(scored_items, key=lambda x: (-x["points"], rank.get(x["code"], 9))):
        text = i["label"]
        if i["detail"]:
            text += f" — {i['detail']}"
        if i["detector"] == "ai":
            text += " (AI-assessed)"
        why.append(text)
    unknowns = [f"{i['label']}: {i['detail'] or 'Unknown'}" for c in cats for i in c["items"]
                if i["state"] == "unknown" and i["code"] != "none"]

    gap_items = [i for i in cats[2]["items"] if i["points"] > 0]
    buying_items = [i for i in cats[3]["items"] if i["points"] > 0]
    top = (gap_items + buying_items + scored_items)
    top_reason = top[0]["label"] + (f" — {top[0]['detail']}" if top[0]["detail"] else "") if top else ""
    pains = pain_points(signals)
    latest_buy = None
    dated = [i for i in cats[3]["items"] if i["state"] == "yes"]
    if dated:
        dated.sort(key=lambda i: i["date"] or "", reverse=True)
        latest_buy = {"code": dated[0]["code"], "label": dated[0]["label"], "date": dated[0]["date"], "detail": dated[0]["detail"]}

    return {
        "opportunity": opportunity, "kard_fit": kard_fit, "business_quality": business_quality,
        "confidence": confidence, "categories": cats,
        "kard_fit_components": fit_components, "quality_components": quality_components,
        "why": why[:10], "unknowns": unknowns, "top_reason": top_reason,
        "pain_points": pains, "top_pain": pains[0]["problem"] if pains else "",
        "latest_buying_signal": latest_buy,
        "buying_signal_count": len([i for i in cats[3]["items"] if i["state"] == "yes"]),
        "weights": dict(weights), "computed_at": N.now_iso(),
    }


PAIN_TEXT = {
    "whatsapp_ordering": "Customers are sent from social media straight into WhatsApp to order or book.",
    "dm_for_price": "Prices and ordering details are handled one-by-one in DMs.",
    "link_in_bio_dependency": "Posts rely on “link in bio” to send customers anywhere.",
    "location_in_captions": "Location and key details are buried in post captions.",
    "scattered_product_info": "Product / service information is scattered across individual posts.",
    "no_contact_on_website": "The website has no clear contact or ordering path.",
    "multi_social_no_hub": "Several social accounts exist, but there is no central hub tying them together.",
    "no_website": "No central website or destination for the brand was found.",
    "weak_website": "The current website is weak or outdated.",
    "no_landing_page": "There is no useful landing page for customers to land on.",
    "weak_link_in_bio": "The bio link is weak or generic.",
}


def pain_points(signals: dict[str, dict]) -> list[dict]:
    order = ["whatsapp_ordering", "dm_for_price", "no_website", "no_landing_page", "weak_link_in_bio",
             "location_in_captions", "scattered_product_info", "multi_social_no_hub", "link_in_bio_dependency",
             "weak_website", "no_contact_on_website"]
    out = []
    for code in order:
        sig = signals.get(code)
        if sig and sig.get("state") == "yes":
            out.append({"code": code, "problem": PAIN_TEXT[code], "detail": sig.get("detail", ""),
                        "evidence": sig.get("evidence", []), "detector": sig.get("detector", "rule")})
    return out


def assess_confidence(lead, signals, observations, cats, settings, ref) -> dict:
    kinds = {o["kind"] for o in observations}
    window = int(settings["social_activity_window_days"])
    sources = []
    if "website" in kinds or lead.get("website_status") == "none_found":
        sources.append("Website checked")
    if lead.get("instagram_handle") and (any((o.get("meta") or {}).get("platform") == "instagram" for o in observations)
                                         or lead.get("followers_instagram") is not None):
        sources.append("Instagram data")
    if lead.get("tiktok_handle") and (any((o.get("meta") or {}).get("platform") == "tiktok" for o in observations)
                                      or lead.get("followers_tiktok") is not None):
        sources.append("TikTok data")
    recent = [o for o in observations if o["kind"] in ("post", "search_snippet")
              and (N.days_since(o.get("observed_at"), ref) is not None and N.days_since(o.get("observed_at"), ref) <= window)]
    if recent:
        sources.append("Recent dated activity")
    if lead.get("whatsapp") or lead.get("phone") or lead.get("email"):
        sources.append("Contact details")
    if kinds & {"search_snippet", "places", "link_in_bio", "manual_note"}:
        sources.append("Other public sources")
    checks = [i for c in cats if c["key"] != "buying_signals" for i in c["items"]]
    unknown = [i for i in checks if i["state"] == "unknown"]
    ratio = len(unknown) / len(checks) if checks else 1
    if len(sources) >= 4 and "Recent dated activity" in sources and "Contact details" in sources and ratio <= 0.35:
        level = "High"
    elif len(sources) >= 2 and ratio <= 0.6:
        level = "Medium"
    else:
        level = "Low"
    missing = [s for s in ["Website checked", "Instagram data", "TikTok data", "Recent dated activity", "Contact details"]
               if s not in sources]
    return {"level": level, "sources": sources, "missing": missing, "unknown_checks": len(unknown),
            "total_checks": len(checks), "unknown_ratio": round(ratio, 2)}
