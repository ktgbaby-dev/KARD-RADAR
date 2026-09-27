"""Signal catalogue + deterministic (rule-based) signal detection.

A signal is a structured fact about a lead: {code, state: yes|no|unknown, detail, evidence, signal_date}.
Evidence references are "obs:<id>" (an observation row) or "field:<column>" (a value on the lead record).
Rules never guess: when data is missing the state is "unknown".
"""
import json
import re
from datetime import date, timedelta

from . import normalize as N
from .settings import match_industry

# --------------------------------------------------------------------------- catalogue
# category: which score category the signal feeds ("pain" and "quality" feed Kard Fit / Business Quality)
# ai: whether the AI layer may propose it (it must cite evidence)
CATALOG = {
    # Business fit (cap 20)
    "nigerian_business": {"category": "business_fit", "points": 5, "label": "Based in the target market", "ai": False},
    "target_industry": {"category": "business_fit", "points": 5, "label": "Fits a target industry", "ai": False},
    "sells_offering": {"category": "business_fit", "points": 5, "label": "Clearly sells a product or service", "ai": True},
    "customer_facing": {"category": "business_fit", "points": 5, "label": "Customer-facing / networking business", "ai": True},
    # Social activity (cap 20)
    "posted_recently": {"category": "social_activity", "points": 5, "label": "Posted recently", "ai": False},
    "consistent_posting": {"category": "social_activity", "points": 5, "label": "Consistent posting", "ai": False},
    "active_social_presence": {"category": "social_activity", "points": 5, "label": "Active Instagram/TikTok presence", "ai": False},
    "audience_engagement": {"category": "social_activity", "points": 5, "label": "Evidence of audience engagement", "ai": True},
    # Digital presence gap (cap 30)
    "no_website": {"category": "digital_gap", "points": 10, "label": "No website found", "ai": False},
    "weak_website": {"category": "digital_gap", "points": 5, "label": "Weak or outdated website", "ai": False},
    "no_landing_page": {"category": "digital_gap", "points": 5, "label": "No useful landing page", "ai": False},
    "weak_link_in_bio": {"category": "digital_gap", "points": 5, "label": "Weak or generic link-in-bio", "ai": False},
    "info_hard_to_find": {"category": "digital_gap", "points": 5, "label": "Key customer information is hard to find", "ai": True},
    # Buying / marketing signals (5 each, cap 20)
    "product_launch": {"category": "buying_signals", "points": 5, "label": "Product launch", "ai": True},
    "new_collection": {"category": "buying_signals", "points": 5, "label": "New collection / new stock", "ai": True},
    "promotion_ads": {"category": "buying_signals", "points": 5, "label": "Advertising / promotion", "ai": True},
    "expansion": {"category": "buying_signals", "points": 5, "label": "Expansion / new location", "ai": True},
    "influencer_collab": {"category": "buying_signals", "points": 5, "label": "Influencer / creator collaboration", "ai": True},
    "event": {"category": "buying_signals", "points": 5, "label": "Event / pop-up", "ai": True},
    "hiring": {"category": "buying_signals", "points": 5, "label": "Hiring", "ai": True},
    "rebrand": {"category": "buying_signals", "points": 5, "label": "Rebrand", "ai": True},
    "frequent_promotions": {"category": "buying_signals", "points": 5, "label": "Frequent promotions", "ai": False},
    "partnership": {"category": "buying_signals", "points": 5, "label": "New partnership", "ai": True},
    "new_service": {"category": "buying_signals", "points": 5, "label": "New service / bookings open", "ai": True},
    "increased_activity": {"category": "buying_signals", "points": 5, "label": "Increased posting activity", "ai": False},
    # Accessibility (cap 10)
    "has_instagram": {"category": "accessibility", "points": 3, "label": "Instagram available", "ai": False},
    "has_tiktok": {"category": "accessibility", "points": 2, "label": "TikTok available", "ai": False},
    "has_whatsapp": {"category": "accessibility", "points": 2, "label": "WhatsApp / phone available", "ai": False},
    "has_email": {"category": "accessibility", "points": 1, "label": "Email available", "ai": False},
    "decision_maker": {"category": "accessibility", "points": 2, "label": "Founder / decision-maker identifiable", "ai": True},
    # Customer-journey friction (feeds "info hard to find", Kard Fit and pain points)
    "dm_for_price": {"category": "pain", "points": 0, "label": "Prices / orders handled in DMs", "ai": True},
    "whatsapp_ordering": {"category": "pain", "points": 0, "label": "Customers pushed into WhatsApp to order or book", "ai": True},
    "link_in_bio_dependency": {"category": "pain", "points": 0, "label": "Posts depend on 'link in bio'", "ai": True},
    "location_in_captions": {"category": "pain", "points": 0, "label": "Location / key details buried in captions", "ai": True},
    "scattered_product_info": {"category": "pain", "points": 0, "label": "Product or service info scattered across posts", "ai": True},
    "no_contact_on_website": {"category": "pain", "points": 0, "label": "Website has no clear contact or order path", "ai": False},
    "multi_social_no_hub": {"category": "pain", "points": 0, "label": "Several social accounts, no central hub", "ai": False},
    # Business-quality indicators
    "strong_visual_branding": {"category": "quality", "points": 0, "label": "Strong visual branding", "ai": True},
    "professional_bio": {"category": "quality", "points": 0, "label": "Clear, professional bio", "ai": True},
}

FRICTION_CODES = ["dm_for_price", "whatsapp_ordering", "link_in_bio_dependency", "location_in_captions",
                  "scattered_product_info", "no_contact_on_website", "multi_social_no_hub"]
BUYING_CODES = [c for c, v in CATALOG.items() if v["category"] == "buying_signals"]
AI_CODES = [c for c, v in CATALOG.items() if v["ai"]]

TEXT_KINDS = {"bio", "post", "search_snippet", "website", "link_in_bio", "manual_note", "places"}

_I = re.I
BUYING_PATTERNS = {
    "new_collection": re.compile(r"\b(new collections?|new arrivals?|just (dropped|landed|arrived)|new drops?|restock(ed)?|back in stock|now in stock|fresh stock|new stock|collection (is )?(out|live|available)|new season)\b", _I),
    "product_launch": re.compile(r"\b(launch(ing|ed|es)?|coming soon|pre-?orders? (are )?(open|now)|pre-?order now|now available|introducing|unveil(ing|ed)?|out now)\b", _I),
    "promotion_ads": re.compile(r"(\b\d{1,2}\s?% off\b|\b(discounts?|promos?|promotion|flash sale|clearance sale|black friday|giveaway|free delivery|special offer|limited offer|offer ends|use code|coupon|buy one get one|mega sale|sales? (is )?(on|live))\b)", _I),
    "expansion": re.compile(r"\b(new (location|branch|outlet|store|office|showroom|studio)|now open|grand opening|opening soon|(second|2nd|third|3rd) (branch|location|outlet)|relocat(ed|ing)|we'?ve moved|expanding|now (in|delivering to|delivering) (abuja|lagos|ibadan|port harcourt|enugu|osogbo|kano|nationwide))\b", _I),
    "influencer_collab": re.compile(r"(\b(collab(oration)?|in collaboration with|brand ambassadors?|influencers?)\b|\b(featuring|ft\.?)\s+@[\w.]+|\bx\s+@[\w.]+)", _I),
    "event": re.compile(r"\b(pop[- ]?up|exhibition|showcase|masterclass|workshop|fashion week|trade fair|bazaar|launch party|live session|rsvp|get your tickets?|tickets? (are )?(now )?(available|on sale|selling))\b", _I),
    "hiring": re.compile(r"\b(we'?re hiring|we are hiring|now hiring|hiring now|vacanc(y|ies)|join our team|job openings?|now recruiting)\b", _I),
    "rebrand": re.compile(r"\b(rebrand(ed|ing)?|new look|new name|new logo)\b", _I),
    "partnership": re.compile(r"\b(partnered with|partnership with|in partnership with|official partner|proud(ly)? partner(ing)? with)\b", _I),
    "new_service": re.compile(r"\b(new services?|now offering|we now (offer|do)|now taking bookings|bookings? (are )?(now )?open|now accepting (orders|bookings))\b", _I),
}
PAIN_PATTERNS = {
    "dm_for_price": re.compile(r"(\b(dm|inbox|pm|message)\s+(us\s+|me\s+)?(for|to (get|know))\s+(the\s+|our\s+)?(price|prices|pricing|rates|cost|details|enquir\w*|inquir\w*|orders?|bookings?)\b|\bprices?\s+(is\s+|are\s+)?in\s+(the\s+)?(dm|inbox|pm)\b|\bpip\b|\bsend\s+(us\s+)?a\s+dm\b|\bdm\s+to\s+(order|book|buy|purchase)\b|\bkindly\s+dm\b|\bdm\s+now\b|\bdm\s+for\s+\w+)", _I),
    "whatsapp_ordering": re.compile(r"((whats\s?app|wa\.me)[^.\n]{0,25}\b(order|orders|book|booking|bookings|enquir\w*|inquir\w*|price|prices|purchase|buy)\b|\b(order|book|enquir\w*|inquir\w*)[^.\n]{0,20}\b(via|on|through|thru)\s+whats\s?app|chat (us|me) on whats\s?app|whats\s?app\s*(us|me)?\s*(on|:)?\s*(\+?234|0)[789])", _I),
    "link_in_bio_dependency": re.compile(r"(\blink\s+in\s+(my\s+|our\s+|the\s+)?bio\b|\bclick (the )?link (in|on) (the |our )?(bio|profile)\b)", _I),
    "location_in_captions": re.compile(r"(📍|\b(visit|find|locate) us (at|in)\b|\baddress\s*[:\-]|\b(our|the) (store|shop|office|studio|outlet|showroom) (is )?(at|located)\b|\blocated at\b)", _I),
}
SELLS_RE = re.compile(r"(₦\s?\d|\bn\d{1,3}(,\d{3})+\b|\bngn\b|\bnaira\b|\b(order|orders|shop|buy|book|booking|bookings|reserve|reservations?|menu|delivery|deliveries|available|services?|for sale|for rent|to let|lease|collections?|appointments?|enquir\w*|quotes?|pre-?orders?|in stock|packages?|rates|prices?)\b)", _I)
ENGAGEMENT_RE = re.compile(r"\b(sold out|restocked due to demand|thank you for (your|the) (order|patronage|support)|happy (clients?|customers?)|client (reviews?|feedback|love)|testimonials?|customers? (love|say))\b", _I)
LIKES_RE = re.compile(r"([\d,.]+\s*[kKmM]?)\s+likes", _I)
COMMENTS_RE = re.compile(r"([\d,.]+\s*[kKmM]?)\s+comments", _I)
DECISION_RE = re.compile(r"(?i:\b(founder|co-?founder|ceo|creative director|owner|managing director|chef|lead stylist)\b)\s*[:\-–|,]?\s*(?:(?i:by)\s+)?(@[\w.]+|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")


def excerpt(text: str, start: int, end: int, width: int = 60) -> str:
    a = max(0, start - width)
    b = min(len(text), end + width)
    s = text[a:b].replace("\n", " ").strip()
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


def _sig(code, state, detail="", evidence=None, signal_date=None):
    return {"code": code, "state": state, "detail": detail, "evidence": list(dict.fromkeys(evidence or []))[:8],
            "signal_date": signal_date.isoformat() if isinstance(signal_date, date) else signal_date}


def _latest(dates):
    ds = [d for d in dates if d]
    return max(ds) if ds else None


def detect(lead: dict, observations: list[dict], settings: dict, ref: date | None = None) -> list[dict]:
    """Run every rule and return one signal per catalogue code that rules can assess."""
    ref = ref or N.today()
    out: dict[str, dict] = {}
    text_obs = [o for o in observations if o["kind"] in TEXT_KINDS and o.get("content")]
    posts = [o for o in observations if o["kind"] == "post"]
    post_dates = sorted([d for d in (N.to_date(o.get("observed_at")) for o in posts) if d], reverse=True)
    social_window = int(settings["social_activity_window_days"])
    recent_days = int(settings["recent_post_days"])
    buy_window = int(settings["buying_signal_window_days"])

    # ------------------------------------------------ pattern matches over evidence text
    def scan(patterns: dict, kinds=None):
        found = {}
        for o in text_obs:
            if kinds and o["kind"] not in kinds:
                continue
            content = o["content"]
            for code, rx in patterns.items():
                m = rx.search(content)
                if not m:
                    continue
                f = found.setdefault(code, {"evidence": [], "dates": [], "quotes": [], "obs": []})
                f["evidence"].append(f"obs:{o['id']}")
                f["dates"].append(N.to_date(o.get("observed_at")))
                f["obs"].append(o)
                if len(f["quotes"]) < 2:
                    f["quotes"].append(excerpt(content, m.start(), m.end()))
        return found

    buying = scan(BUYING_PATTERNS)
    pains = scan({k: v for k, v in PAIN_PATTERNS.items() if k != "location_in_captions"})
    pains.update(scan({"location_in_captions": PAIN_PATTERNS["location_in_captions"]}, kinds={"post"}))

    for code, f in buying.items():
        d = _latest(f["dates"])
        out[code] = _sig(code, "yes", "“" + f["quotes"][0] + "”", f["evidence"], d)

    # frequent promotions: promo language in 3+ separate observations inside the window
    promo = buying.get("promotion_ads")
    if promo:
        in_window = [d for d in promo["dates"] if d and (ref - d).days <= buy_window]
        if len(in_window) >= 3:
            out["frequent_promotions"] = _sig("frequent_promotions", "yes",
                                              f"Promotional posts on {len(in_window)} separate occasions in the last {buy_window} days",
                                              promo["evidence"], max(in_window))

    # increased activity: more posts in the last 14 days than the 14 before (needs dated posts in both)
    last14 = [d for d in post_dates if 0 <= (ref - d).days < 14]
    prev14 = [d for d in post_dates if 14 <= (ref - d).days < 28]
    if len(last14) >= 4 and len(prev14) >= 1 and len(last14) >= 2 * len(prev14):
        out["increased_activity"] = _sig("increased_activity", "yes",
                                         f"{len(last14)} posts in the last 14 days vs {len(prev14)} in the 14 days before",
                                         [f"obs:{o['id']}" for o in posts][:6], last14[0])

    for code, f in pains.items():
        out[code] = _sig(code, "yes", "“" + f["quotes"][0] + "”", f["evidence"], _latest(f["dates"]))

    # ------------------------------------------------ business fit
    country = (lead.get("country") or "").strip()
    target_country = settings.get("target_country", "Nigeria")
    city = (lead.get("city") or "").strip()
    pkey = lead.get("phone_key") or N.phone_key(lead.get("whatsapp") or "")
    in_target_city = city and (N.state_for_city(city) or city.lower() in [c.lower() for c in settings["target_cities"]])
    if country and country.lower() == target_country.lower():
        out["nigerian_business"] = _sig("nigerian_business", "yes", f"Country on record: {country}", ["field:country"])
    elif country:
        out["nigerian_business"] = _sig("nigerian_business", "no", f"Country on record is {country}, not {target_country}", ["field:country"])
    elif in_target_city and target_country.lower() == "nigeria":
        out["nigerian_business"] = _sig("nigerian_business", "yes", f"Located in {city}", ["field:city"])
    elif pkey.startswith("234") and target_country.lower() == "nigeria":
        out["nigerian_business"] = _sig("nigerian_business", "yes", "Nigerian (+234) phone number", ["field:phone"])
    else:
        out["nigerian_business"] = _sig("nigerian_business", "unknown", "No country, city or phone on record")

    industry = (lead.get("industry") or "").strip()
    ind = match_industry(settings, industry)
    if ind:
        out["target_industry"] = _sig("target_industry", "yes", f"{ind['name']} is a target industry", ["field:industry"])
        if ind.get("customer_facing"):
            out["customer_facing"] = _sig("customer_facing", "yes", f"{ind['name']} businesses serve customers directly", ["field:industry"])
    elif industry:
        out["target_industry"] = _sig("target_industry", "no", f"“{industry}” is not in the target industry list", ["field:industry"])
    else:
        out["target_industry"] = _sig("target_industry", "unknown", "Industry not set")
    out.setdefault("customer_facing", _sig("customer_facing", "unknown", "Could not tell from the industry"))

    sells = []
    for o in text_obs:
        m = SELLS_RE.search(o["content"])
        if m:
            sells.append((o, m))
    if sells:
        o, m = sells[0]
        out["sells_offering"] = _sig("sells_offering", "yes", "“" + excerpt(o["content"], m.start(), m.end(), 45) + "”",
                                     [f"obs:{x['id']}" for x, _ in sells])
    else:
        out["sells_offering"] = _sig("sells_offering", "unknown", "No offer, price or order language in the evidence yet")

    # ------------------------------------------------ social activity
    has_ig, has_tt = bool(lead.get("instagram_handle")), bool(lead.get("tiktok_handle"))
    post_refs = [f"obs:{o['id']}" for o in posts][:8]
    stats = [o for o in observations if o["kind"] == "social_stats"]
    stated_ppw = None
    for o in stats:
        meta = o.get("meta") or {}
        if meta.get("posts_per_week") not in (None, ""):
            try:
                stated_ppw = float(meta["posts_per_week"])
            except (TypeError, ValueError):
                pass
    if post_dates:
        age = (ref - post_dates[0]).days
        if age <= recent_days:
            out["posted_recently"] = _sig("posted_recently", "yes", f"Last known post {age} day(s) ago ({post_dates[0].isoformat()})", post_refs, post_dates[0])
        else:
            out["posted_recently"] = _sig("posted_recently", "no", f"Last known post {age} days ago ({post_dates[0].isoformat()})", post_refs, post_dates[0])
    else:
        out["posted_recently"] = _sig("posted_recently", "unknown", "No dated posts recorded — add a social snapshot")

    in_window = [d for d in post_dates if (ref - d).days <= social_window]
    if len(in_window) >= 4:
        out["consistent_posting"] = _sig("consistent_posting", "yes", f"{len(in_window)} posts in the last {social_window} days", post_refs)
    elif stated_ppw is not None and stated_ppw >= 1:
        out["consistent_posting"] = _sig("consistent_posting", "yes", f"About {stated_ppw:g} posts per week (from social snapshot)",
                                         [f"obs:{o['id']}" for o in stats])
    elif post_dates and len(in_window) < 2 and (stated_ppw is None or stated_ppw < 1):
        out["consistent_posting"] = _sig("consistent_posting", "no", f"Only {len(in_window)} known post(s) in the last {social_window} days", post_refs)
    elif stated_ppw is not None:
        out["consistent_posting"] = _sig("consistent_posting", "no", f"About {stated_ppw:g} posts per week", [f"obs:{o['id']}" for o in stats])
    else:
        out["consistent_posting"] = _sig("consistent_posting", "unknown", "Not enough dated posts to judge consistency")

    followers = max(lead.get("followers_instagram") or 0, lead.get("followers_tiktok") or 0)
    posts_count = 0
    for o in stats:
        try:
            posts_count = max(posts_count, int((o.get("meta") or {}).get("posts_count") or 0))
        except (TypeError, ValueError):
            pass
    if has_ig or has_tt:
        platforms = " + ".join(p for p, ok in (("Instagram", has_ig), ("TikTok", has_tt)) if ok)
        if in_window or posts_count >= 12 or followers >= 300:
            reason = []
            if in_window:
                reason.append(f"{len(in_window)} recent post(s)")
            if posts_count >= 12:
                reason.append(f"{posts_count} posts total")
            if followers >= 300:
                reason.append(f"{followers:,} followers ({lead.get('followers_source') or 'source not recorded'})")
            out["active_social_presence"] = _sig("active_social_presence", "yes", f"{platforms}: " + ", ".join(reason),
                                                 ["field:instagram_url" if has_ig else "field:tiktok_url", *post_refs[:3]])
        elif post_dates and (ref - post_dates[0]).days > 90:
            out["active_social_presence"] = _sig("active_social_presence", "no",
                                                 f"{platforms} looks dormant (no posts for {(ref - post_dates[0]).days} days)", post_refs)
        else:
            out["active_social_presence"] = _sig("active_social_presence", "unknown",
                                                 f"{platforms} on record but no activity data yet")
    else:
        out["active_social_presence"] = _sig("active_social_presence", "unknown", "No Instagram or TikTok profile on record")

    engaged = []
    low_engagement = None
    for o in observations:
        meta = o.get("meta") or {}
        if o["kind"] == "engagement":
            likes = _num(meta.get("avg_likes"))
            comments = _num(meta.get("avg_comments"))
            if (likes or 0) >= 20 or (comments or 0) >= 3:
                engaged.append((o, f"Average {likes or 0:g} likes / {comments or 0:g} comments per post"))
            elif likes is not None or comments is not None:
                low_engagement = (o, f"Low engagement: about {likes or 0:g} likes / {comments or 0:g} comments per post")
            continue
        if o["kind"] not in TEXT_KINDS or not o.get("content"):
            continue
        c = o["content"]
        lm, cm = LIKES_RE.search(c), COMMENTS_RE.search(c)
        if (lm and (N.parse_count(lm[1]) or 0) >= 20) or (cm and (N.parse_count(cm[1]) or 0) >= 3):
            m = lm or cm
            engaged.append((o, "“" + excerpt(c, m.start(), m.end(), 30) + "”"))
            continue
        m = ENGAGEMENT_RE.search(c)
        if m:
            engaged.append((o, "“" + excerpt(c, m.start(), m.end(), 40) + "”"))
    if engaged:
        out["audience_engagement"] = _sig("audience_engagement", "yes", engaged[0][1], [f"obs:{o['id']}" for o, _ in engaged])
    elif low_engagement:
        out["audience_engagement"] = _sig("audience_engagement", "no", low_engagement[1], [f"obs:{low_engagement[0]['id']}"])
    else:
        out["audience_engagement"] = _sig("audience_engagement", "unknown", "No likes, comments or customer feedback recorded")

    # ------------------------------------------------ digital presence gap
    ws = lead.get("website_status") or "unknown"
    quality = lead.get("website_quality")
    lib = lead.get("link_in_bio_type") or "unknown"
    lib_url = lead.get("link_in_bio_url") or ""
    web_refs = ["field:website_status"]
    website_obs = [f"obs:{o['id']}" for o in observations if o["kind"] in ("website", "website_check")]

    if ws == "none_found":
        out["no_website"] = _sig("no_website", "yes", lead.get("website_evidence") or "No website found", web_refs + website_obs)
    elif ws in ("has_website", "unreachable", "parked"):
        out["no_website"] = _sig("no_website", "no", f"Website on record: {lead.get('website_domain') or lead.get('website_url')}", ["field:website_url"])
    else:
        out["no_website"] = _sig("no_website", "unknown", "Website not checked yet")

    weak_threshold = 55
    if ws in ("parked", "unreachable"):
        label = "parked / placeholder page" if ws == "parked" else "did not load"
        out["weak_website"] = _sig("weak_website", "yes", f"Website {label}", ["field:website_status"] + website_obs)
    elif ws == "has_website" and quality is not None:
        if quality < weak_threshold:
            out["weak_website"] = _sig("weak_website", "yes", f"Website quality {quality}/100", ["field:website_quality"] + website_obs)
        else:
            out["weak_website"] = _sig("weak_website", "no", f"Website quality {quality}/100", ["field:website_quality"] + website_obs)
    elif ws == "none_found":
        out["weak_website"] = _sig("weak_website", "no", "No website to assess (counted under “No website found”)")
    else:
        out["weak_website"] = _sig("weak_website", "unknown", "Website not analysed yet")

    no_good_site = ws in ("none_found", "parked", "unreachable") or (ws == "has_website" and quality is not None and quality < weak_threshold)
    good_site = ws == "has_website" and quality is not None and quality >= weak_threshold
    if good_site:
        out["no_landing_page"] = _sig("no_landing_page", "no", "The website works as a landing page", ["field:website_quality"])
    elif lib == "storefront":
        out["no_landing_page"] = _sig("no_landing_page", "no", "Bio link goes to an online storefront", ["field:link_in_bio_url"])
    elif no_good_site and lib in ("none", "whatsapp", "generic_link_page", "social", "own_website"):
        what = {"none": "no bio link", "whatsapp": "a WhatsApp link", "generic_link_page": "a generic link list",
                "social": "another social profile", "own_website": "the weak website"}[lib]
        out["no_landing_page"] = _sig("no_landing_page", "yes", f"No working website and the bio offers {what}",
                                      ["field:website_status", "field:link_in_bio_url"])
    else:
        out["no_landing_page"] = _sig("no_landing_page", "unknown", "Need both website status and bio link to judge")

    host = N.host_of(lib_url)
    if lib == "none":
        out["weak_link_in_bio"] = _sig("weak_link_in_bio", "yes", "No link in bio", ["field:link_in_bio_url"])
    elif lib == "whatsapp":
        out["weak_link_in_bio"] = _sig("weak_link_in_bio", "yes", "Bio link opens WhatsApp directly — nothing to browse first", ["field:link_in_bio_url"])
    elif lib == "generic_link_page":
        out["weak_link_in_bio"] = _sig("weak_link_in_bio", "yes", f"Generic link-list page ({host})", ["field:link_in_bio_url"])
    elif lib == "social":
        out["weak_link_in_bio"] = _sig("weak_link_in_bio", "yes", f"Bio link points to another social profile ({host})", ["field:link_in_bio_url"])
    elif lib in ("own_website", "storefront"):
        state = "yes" if (lib == "own_website" and no_good_site) else "no"
        detail = f"Bio links to {host}" + (" (a weak website)" if state == "yes" else "")
        out["weak_link_in_bio"] = _sig("weak_link_in_bio", state, detail, ["field:link_in_bio_url"])
    else:
        out["weak_link_in_bio"] = _sig("weak_link_in_bio", "unknown", "Bio link not recorded")

    # friction derived from structured data
    other = lead.get("other_socials") or {}
    if isinstance(other, str):
        try:
            other = json.loads(other) if other.strip() else {}
        except ValueError:
            other = {}
    profile_count = sum([has_ig, has_tt]) + len([k for k, v in other.items() if v])
    if profile_count >= 2 and no_good_site:
        out["multi_social_no_hub"] = _sig("multi_social_no_hub", "yes",
                                          f"{profile_count} social profiles but no working website tying them together",
                                          ["field:instagram_url", "field:tiktok_url", "field:website_status"])
    website_contact = [o for o in observations if o["kind"] == "website" and (o.get("meta") or {}).get("has_contact") is False]
    if ws == "has_website" and website_contact:
        out["no_contact_on_website"] = _sig("no_contact_on_website", "yes", "No phone, email, WhatsApp or contact link on the homepage",
                                            [f"obs:{website_contact[0]['id']}"])

    friction = [c for c in FRICTION_CODES if out.get(c, {}).get("state") == "yes"
                and not (c == "whatsapp_ordering" and good_site)]
    if friction:
        labels = "; ".join(CATALOG[c]["label"] for c in friction[:3])
        ev = []
        for c in friction:
            ev.extend(out[c]["evidence"])
        out["info_hard_to_find"] = _sig("info_hard_to_find", "yes", labels, ev)
    elif good_site and not website_contact:
        out["info_hard_to_find"] = _sig("info_hard_to_find", "no", "Website presents contact and key information", ["field:website_quality"])
    else:
        out["info_hard_to_find"] = _sig("info_hard_to_find", "unknown", "No customer-journey friction observed yet")

    # ------------------------------------------------ accessibility
    out["has_instagram"] = _sig("has_instagram", "yes" if has_ig else "no",
                                f"@{lead['instagram_handle']}" if has_ig else "No Instagram on record", ["field:instagram_url"] if has_ig else [])
    out["has_tiktok"] = _sig("has_tiktok", "yes" if has_tt else "no",
                             f"@{lead['tiktok_handle']}" if has_tt else "No TikTok on record", ["field:tiktok_url"] if has_tt else [])
    wa = lead.get("whatsapp") or lead.get("phone")
    out["has_whatsapp"] = _sig("has_whatsapp", "yes" if wa else "no", wa or "No WhatsApp or phone on record",
                               ["field:whatsapp" if lead.get("whatsapp") else "field:phone"] if wa else [])
    out["has_email"] = _sig("has_email", "yes" if lead.get("email") else "no", lead.get("email") or "No email on record",
                            ["field:email"] if lead.get("email") else [])
    if lead.get("founder_name"):
        out["decision_maker"] = _sig("decision_maker", "yes", f"{lead['founder_name']}", ["field:founder_name"])
    else:
        hit = None
        for o in text_obs:
            m = DECISION_RE.search(o["content"])
            if m:
                hit = (o, m)
                break
        if hit:
            o, m = hit
            out["decision_maker"] = _sig("decision_maker", "yes", "“" + excerpt(o["content"], m.start(), m.end(), 25) + "”", [f"obs:{o['id']}"])
        else:
            out["decision_maker"] = _sig("decision_maker", "unknown", "Founder / owner not identified yet")

    # ------------------------------------------------ quality indicators
    bios = [o for o in observations if o["kind"] == "bio" and o.get("content")]
    if bios:
        b = bios[0]
        text = b["content"]
        has_offer = bool(SELLS_RE.search(text))
        has_where = bool(re.search(r"(📍|\b(lagos|abuja|ibadan|osogbo|port harcourt|enugu|nigeria|nationwide|delivery)\b)", text, re.I))
        has_contact = bool(re.search(r"(whats\s?app|📞|☎|\+?234|\b0[789][01]\d{8}\b|@\w+\.\w+|email)", text, re.I))
        if len(text) >= 40 and has_offer and (has_where or has_contact):
            out["professional_bio"] = _sig("professional_bio", "yes", "Bio states the offer and how/where to buy", [f"obs:{b['id']}"])
    return list(out.values())


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def snippet_signals(text: str) -> list[str]:
    """Cheap pre-screen used on discovery candidates (search snippets)."""
    codes = []
    for code, rx in {**BUYING_PATTERNS, **PAIN_PATTERNS}.items():
        if rx.search(text or ""):
            codes.append(code)
    return codes


def resolve(rows: list[dict]) -> dict[str, dict]:
    """Collapse rule / AI / manual rows into one effective signal per code.
    Precedence: manual (any state) > rule 'yes' > rule 'no' > AI 'yes' > rule 'unknown'.
    AI can therefore only fill gaps the rules could not assess; it never overrides observed data."""
    by_code: dict[str, list[dict]] = {}
    for r in rows:
        by_code.setdefault(r["code"], []).append(r)
    out = {}
    for code, items in by_code.items():
        manual = [r for r in items if r["detector"] == "manual"]
        rule = [r for r in items if r["detector"] == "rule"]
        ai = [r for r in items if r["detector"] == "ai" and r["state"] == "yes"]
        if manual:
            chosen = manual[-1]
        elif any(r["state"] == "yes" for r in rule):
            chosen = next(r for r in rule if r["state"] == "yes")
        elif any(r["state"] == "no" for r in rule):
            chosen = next(r for r in rule if r["state"] == "no")
        elif ai:
            chosen = ai[0]
        elif rule:
            chosen = rule[0]
        else:
            continue
        out[code] = chosen
    return out
