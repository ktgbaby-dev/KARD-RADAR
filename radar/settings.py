"""Kard strategy settings: scoring weights, target markets, thresholds. Stored in the `settings` table."""
import copy

from .db import Conn, dumps, loads
from .normalize import now_iso

CATEGORY_KEYS = ["business_fit", "social_activity", "digital_gap", "buying_signals", "accessibility"]

DEFAULT_INDUSTRIES = [
    {"name": "Fashion", "customer_facing": True,
     "keywords": ["fashion", "clothing", "boutique", "apparel", "ready to wear", "rtw", "aso ebi", "tailor", "native wear", "streetwear"]},
    {"name": "Beauty", "customer_facing": True,
     "keywords": ["beauty", "makeup", "mua", "skincare", "spa", "nails", "lashes", "brows", "cosmetics"]},
    {"name": "Hair & wigs", "customer_facing": True,
     "keywords": ["hair", "wigs", "wig", "braids", "salon", "frontal", "bundles", "barber"]},
    {"name": "Jewelry", "customer_facing": True, "keywords": ["jewelry", "jewellery", "gold", "beads", "accessories", "watches"]},
    {"name": "Restaurants", "customer_facing": True, "keywords": ["restaurant", "food", "kitchen", "grill", "suya", "chops", "eatery", "catering"]},
    {"name": "Cafés", "customer_facing": True, "keywords": ["cafe", "café", "coffee", "bakery", "pastries", "brunch", "desserts"]},
    {"name": "Hotels", "customer_facing": True, "keywords": ["hotel", "suites", "apartments", "shortlet", "short let", "lodge", "resort"]},
    {"name": "Hospitality", "customer_facing": True, "keywords": ["lounge", "bar", "club", "hospitality", "beach", "rooftop"]},
    {"name": "Real estate", "customer_facing": True, "keywords": ["real estate", "realtor", "properties", "property", "homes", "land", "estate"]},
    {"name": "Interior design", "customer_facing": True, "keywords": ["interior", "interiors", "decor", "furniture", "design studio"]},
    {"name": "Photography", "customer_facing": True, "keywords": ["photography", "photographer", "studio", "portraits", "shoot"]},
    {"name": "Videography", "customer_facing": True, "keywords": ["videography", "videographer", "films", "cinematography", "video production"]},
    {"name": "Events", "customer_facing": True, "keywords": ["events", "event planner", "wedding planner", "decor", "rentals", "party", "mc"]},
    {"name": "Fitness", "customer_facing": True, "keywords": ["fitness", "gym", "trainer", "pilates", "yoga", "wellness"]},
    {"name": "Automotive", "customer_facing": True, "keywords": ["cars", "auto", "automotive", "car dealer", "spare parts", "car wash", "detailing"]},
    {"name": "Creative business", "customer_facing": True, "keywords": ["art", "artist", "creative", "design", "branding", "illustration", "gallery"]},
    {"name": "Technology & services", "customer_facing": True, "keywords": ["tech", "software", "it services", "agency", "digital", "logistics"]},
    {"name": "Consultants", "customer_facing": True, "keywords": ["consultant", "consulting", "advisory", "legal", "accounting"]},
    {"name": "Coaches", "customer_facing": True, "keywords": ["coach", "coaching", "mentor", "trainer", "course"]},
    {"name": "Artisans", "customer_facing": True, "keywords": ["handmade", "artisan", "crafts", "leather", "shoemaker", "adire", "bags"]},
    {"name": "Personal brands", "customer_facing": True, "keywords": ["influencer", "creator", "speaker", "author", "personal brand"]},
    {"name": "Other customer-facing", "customer_facing": True, "keywords": []},
]

DEFAULTS = {
    "weights": {"business_fit": 20, "social_activity": 20, "digital_gap": 30, "buying_signals": 20, "accessibility": 10},
    "target_country": "Nigeria",
    "target_cities": ["Lagos", "Abuja", "Ibadan", "Osogbo", "Port Harcourt", "Enugu", "Benin City", "Kano",
                      "Abeokuta", "Uyo", "Owerri", "Kaduna", "Ilorin", "Warri"],
    "target_industries": DEFAULT_INDUSTRIES,
    "min_opportunity_score": 65,
    "high_opportunity_score": 80,
    "buying_signal_window_days": 30,
    "social_activity_window_days": 30,
    "recent_post_days": 10,
    "today_count": 20,
    "research_cache_days": 7,
    "auto_qualify": True,
}


class SettingsError(ValueError):
    pass


def get_settings(conn: Conn) -> dict:
    s = copy.deepcopy(DEFAULTS)
    for row in conn.all("SELECT key, value FROM settings"):
        if row["key"] in s:
            s[row["key"]] = loads(row["value"], s[row["key"]])
    return s


def validate(data: dict) -> dict:
    """Validate a (partial) settings update and return the cleaned values."""
    out = {}
    if "weights" in data:
        w = data["weights"]
        if not isinstance(w, dict) or set(w) != set(CATEGORY_KEYS):
            raise SettingsError("Weights must include exactly: " + ", ".join(CATEGORY_KEYS))
        clean = {}
        for k in CATEGORY_KEYS:
            try:
                v = int(w[k])
            except (TypeError, ValueError):
                raise SettingsError(f"Weight for {k} must be a whole number")
            if v < 0 or v > 100:
                raise SettingsError(f"Weight for {k} must be between 0 and 100")
            clean[k] = v
        if sum(clean.values()) != 100:
            raise SettingsError(f"Weights must total 100 (currently {sum(clean.values())})")
        out["weights"] = clean
    if "target_cities" in data:
        cities = [str(c).strip() for c in data["target_cities"] if str(c).strip()]
        if not cities:
            raise SettingsError("Add at least one target city")
        out["target_cities"] = list(dict.fromkeys(cities))[:200]
    if "target_country" in data:
        country = str(data["target_country"]).strip()
        if not country:
            raise SettingsError("Target country is required")
        out["target_country"] = country[:60]
    if "target_industries" in data:
        inds = []
        seen = set()
        for item in data["target_industries"]:
            if isinstance(item, str):
                item = {"name": item}
            name = str(item.get("name", "")).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            kws = [str(k).strip().lower() for k in item.get("keywords", []) if str(k).strip()]
            inds.append({"name": name[:60], "customer_facing": bool(item.get("customer_facing", True)),
                         "keywords": kws[:40]})
        if not inds:
            raise SettingsError("Add at least one target industry")
        out["target_industries"] = inds
    ranges = {
        "min_opportunity_score": (0, 100), "high_opportunity_score": (1, 100),
        "buying_signal_window_days": (1, 365), "social_activity_window_days": (1, 365),
        "recent_post_days": (1, 90), "today_count": (5, 100), "research_cache_days": (0, 90),
    }
    for key, (lo, hi) in ranges.items():
        if key in data:
            try:
                v = int(data[key])
            except (TypeError, ValueError):
                raise SettingsError(f"{key} must be a whole number")
            if not lo <= v <= hi:
                raise SettingsError(f"{key} must be between {lo} and {hi}")
            out[key] = v
    if "auto_qualify" in data:
        out["auto_qualify"] = bool(data["auto_qualify"])
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise SettingsError("Unknown setting(s): " + ", ".join(sorted(unknown)))
    return out


def save_settings(conn: Conn, data: dict) -> dict:
    clean = validate(data)
    ts = now_iso()
    for key, value in clean.items():
        conn.run("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                 [key, dumps(value), ts])
    return get_settings(conn)


def match_industry(settings: dict, text: str) -> dict | None:
    """Find the configured industry matching a name or free text (exact name first, then keywords)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for ind in settings["target_industries"]:
        if ind["name"].lower() == t:
            return ind
    for ind in settings["target_industries"]:
        for kw in ind.get("keywords", []):
            if kw and (t == kw or f" {kw} " in f" {t} "):
                return ind
    return None
