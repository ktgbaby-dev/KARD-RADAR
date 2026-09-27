"""Normalization helpers: URLs, handles, phones, names, dates. Pure functions, no I/O."""
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------- time

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today() -> date:
    return datetime.now(timezone.utc).date()


def to_date(value) -> date | None:
    """Parse an ISO date/datetime string (or date) into a date. Returns None when unknown."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return parse_loose_date(s)


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_loose_date(text: str, ref: date | None = None) -> date | None:
    """Parse dates as they appear in search results, CSVs and pasted captions.
    Supports ISO, DD/MM/YYYY, 'Sep 20, 2026', '20 Sep 2026', '3 days ago', 'yesterday'."""
    if not text:
        return None
    ref = ref or today()
    s = text.strip().lower()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
    if m:  # Nigeria uses day-first dates
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    if s in ("today", "just now"):
        return ref
    if s == "yesterday":
        return ref - timedelta(days=1)
    m = re.match(r"^(\d+|an?|one)\s+(minute|hour|day|week|month|year)s?\s+ago", s)
    if m:
        n = 1 if m[1] in ("a", "an", "one") else int(m[1])
        unit = m[2]
        days = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        return ref - timedelta(days=days)
    m = re.match(r"^([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m[1] in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[1]], int(m[2]))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})\s+([a-z]{3})[a-z]*\.?,?\s+(\d{4})", s)
    if m and m[2] in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[2]], int(m[1]))
        except ValueError:
            return None
    return None


def days_since(value, ref: date | None = None) -> int | None:
    d = to_date(value)
    if d is None:
        return None
    return ((ref or today()) - d).days


# ---------------------------------------------------------------- text

def clean_text(value, limit: int = 0) -> str:
    s = "" if value is None else str(value)
    s = s.replace("\x00", "").strip()
    if limit and len(s) > limit:
        s = s[:limit]
    return s


_NAME_NOISE = {
    "ltd", "limited", "llc", "inc", "plc", "nig", "nigeria", "ng", "official", "the", "enterprises",
    "enterprise", "ventures", "co", "company", "intl", "international",
}


def name_key(name: str) -> str:
    """Normalized business-name key used for duplicate detection."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    words = [w for w in s.split() if w not in _NAME_NOISE]
    if not words:  # a name made only of noise words, keep it rather than returning nothing
        words = s.split()
    return "".join(words)


def title_case_handle(handle: str) -> str:
    words = re.split(r"[._]+", handle or "")
    return " ".join(w.capitalize() for w in words if w)


# ---------------------------------------------------------------- urls

def clean_url(value: str) -> str:
    s = clean_text(value, 2048)
    if not s:
        return ""
    s = s.strip("<>\"' ")
    if s.startswith("@"):
        return s
    if not re.match(r"^[a-z][a-z0-9+.-]*://", s, re.I):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", s, re.I):
            s = "https://" + s
        else:
            return s
    return s


def host_of(url: str) -> str:
    try:
        host = (urlparse(clean_url(url)).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


# Hosts where the host alone does not identify a business (path identifies it, or it is a platform).
PLATFORM_HOSTS = {
    "instagram.com", "tiktok.com", "facebook.com", "fb.com", "m.facebook.com", "x.com", "twitter.com",
    "threads.net", "youtube.com", "youtu.be", "linkedin.com", "pinterest.com", "snapchat.com",
    "wa.me", "whatsapp.com", "api.whatsapp.com", "wa.link", "linktr.ee", "beacons.ai", "bio.link", "lnk.bio",
    "linkin.bio", "taplink.cc", "many.link", "solo.to", "campsite.bio", "hoo.be", "bit.ly", "tinyurl.com",
    "t.co", "cutt.ly", "rb.gy", "goo.gl", "google.com", "maps.google.com", "maps.app.goo.gl", "g.page",
    "selar.co", "selar.com", "paystack.shop", "paystack.com", "flutterwave.com", "store.flutterwave.com",
    "jiji.ng", "jumia.com.ng", "konga.com", "gmail.com", "yahoo.com", "vconnect.com", "businesslist.com.ng",
    "finelib.com", "tripadvisor.com", "booking.com", "airbnb.com", "nigeriapropertycentre.com",
    "propertypro.ng", "calendly.com", "wixsite.com",
}
# Platforms where each business gets its own subdomain (so the full host IS a business key).
SUBDOMAIN_PLATFORMS = ("bumpa.shop", "mybumpa.com", "myshopify.com", "carrd.co", "business.site",
                       "wixsite.com", "blogspot.com", "wordpress.com", "square.site", "godaddysites.com")

LINK_PAGE_HOSTS = {"linktr.ee", "beacons.ai", "bio.link", "lnk.bio", "linkin.bio", "taplink.cc", "many.link",
                   "solo.to", "campsite.bio", "hoo.be", "linkr.bio", "allmylinks.com", "direct.me"}
SHORTENER_HOSTS = {"bit.ly", "tinyurl.com", "t.co", "cutt.ly", "rb.gy", "goo.gl", "tiny.cc", "shorturl.at"}
WHATSAPP_HOSTS = {"wa.me", "whatsapp.com", "api.whatsapp.com", "wa.link", "chat.whatsapp.com"}
STOREFRONT_HOSTS = {"selar.co", "selar.com", "paystack.shop", "store.flutterwave.com", "flutterwave.com"}
SOCIAL_HOSTS = {"instagram.com": "instagram", "tiktok.com": "tiktok", "facebook.com": "facebook",
                "fb.com": "facebook", "m.facebook.com": "facebook", "x.com": "x", "twitter.com": "x",
                "youtube.com": "youtube", "youtu.be": "youtube", "linkedin.com": "linkedin",
                "threads.net": "threads", "pinterest.com": "pinterest", "snapchat.com": "snapchat"}
DIRECTORY_HOSTS = {"vconnect.com", "businesslist.com.ng", "finelib.com", "jiji.ng", "tripadvisor.com",
                   "nigeriapropertycentre.com", "propertypro.ng", "yelp.com", "foursquare.com"}


def business_domain(url: str) -> str:
    """Dedupe key for a business's own website. Empty for platforms / shared hosts."""
    host = host_of(url)
    if not host:
        return ""
    for suffix in SUBDOMAIN_PLATFORMS:
        if host.endswith("." + suffix):
            return host
    if host in PLATFORM_HOSTS or any(host.endswith("." + p) for p in PLATFORM_HOSTS):
        return ""
    return host


def classify_url(url: str) -> str:
    """Classify a URL: instagram, tiktok, facebook, x, youtube, linkedin, whatsapp, link_page,
    shortener, storefront, maps, directory, website."""
    host = host_of(url)
    if not host:
        return "unknown"
    if host in SOCIAL_HOSTS:
        return SOCIAL_HOSTS[host]
    for h, name in SOCIAL_HOSTS.items():
        if host.endswith("." + h):
            return name
    if host in WHATSAPP_HOSTS:
        return "whatsapp"
    if host in LINK_PAGE_HOSTS:
        return "link_page"
    if host in SHORTENER_HOSTS:
        return "shortener"
    if host in STOREFRONT_HOSTS or host.endswith(".bumpa.shop") or host.endswith(".mybumpa.com") \
            or host.endswith(".myshopify.com") or host.endswith(".paystack.shop"):
        return "storefront"
    if host in ("maps.google.com", "maps.app.goo.gl", "g.page", "goo.gl") or (
            host == "google.com" and "/maps" in url):
        return "maps"
    if host in DIRECTORY_HOSTS:
        return "directory"
    return "website"


def link_in_bio_type(url: str, own_domain: str = "") -> str:
    """Map a bio link onto the categories the scoring engine understands."""
    if not url:
        return "unknown"
    kind = classify_url(url)
    if kind == "website":
        return "own_website"
    if kind == "link_page":
        return "generic_link_page"
    if kind == "whatsapp":
        return "whatsapp"
    if kind == "storefront":
        return "storefront"
    if kind == "shortener":
        return "shortener"
    if kind in SOCIAL_HOSTS.values():
        return "social"
    return "unknown"


_IG_RESERVED = {"p", "reel", "reels", "explore", "stories", "tv", "accounts", "about", "legal", "direct",
                "developer", "web", "tags", "locations", "s"}
_HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}$")


def instagram_handle(value: str) -> str:
    s = clean_text(value)
    if not s:
        return ""
    if s.startswith("@"):
        h = s[1:].lower()
        return h if _HANDLE_RE.match(h) else ""
    if "instagram.com" not in s.lower():
        h = s.lower()
        return h if _HANDLE_RE.match(h) and "." not in h[-4:] else ""
    try:
        path = urlparse(clean_url(s)).path
    except ValueError:
        return ""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return ""
    if parts[0].lower() == "stories" and len(parts) > 1:
        parts = parts[1:]
    h = parts[0].lower().lstrip("@")
    if h in _IG_RESERVED or not _HANDLE_RE.match(h):
        return ""
    return h


def tiktok_handle(value: str) -> str:
    s = clean_text(value)
    if not s:
        return ""
    if s.startswith("@"):
        h = s[1:].lower()
        return h if re.match(r"^[a-z0-9._]{2,24}$", h) else ""
    if "tiktok.com" not in s.lower():
        h = s.lower()
        return h if re.match(r"^[a-z0-9._]{2,24}$", h) and "." not in h[-4:] else ""
    m = re.search(r"tiktok\.com/@([A-Za-z0-9._]{2,24})", s)
    return m[1].lower() if m else ""


def instagram_url(handle: str) -> str:
    return f"https://www.instagram.com/{handle}/" if handle else ""


def tiktok_url(handle: str) -> str:
    return f"https://www.tiktok.com/@{handle}" if handle else ""


# ---------------------------------------------------------------- contact

def phone_key(value: str, default_cc: str = "234") -> str:
    """Normalize to E.164 digits (no plus) for dedupe, e.g. 08031234567 -> 2348031234567."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith(default_cc) and len(digits) >= 12:
        return digits
    if digits.startswith("0") and len(digits) == 11:
        return default_cc + digits[1:]
    if len(digits) == 10 and digits[0] in "789":
        return default_cc + digits
    return digits if len(digits) >= 8 else ""


def pretty_phone(key: str) -> str:
    return "+" + key if key else ""


def whatsapp_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(clean_url(url))
    except ValueError:
        return ""
    host = (p.hostname or "").lower().removeprefix("www.")
    if host == "wa.me":
        return phone_key(p.path.strip("/").split("/")[0])
    if host in ("api.whatsapp.com", "whatsapp.com", "web.whatsapp.com"):
        phone = parse_qs(p.query).get("phone", [""])[0]
        return phone_key(phone)
    return ""


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def clean_email(value: str) -> str:
    s = clean_text(value).lower().removeprefix("mailto:").split("?")[0]
    if not EMAIL_RE.fullmatch(s):
        return ""
    if re.search(r"\.(png|jpe?g|gif|webp|svg)$", s) or s.endswith("example.com") or "sentry" in s:
        return ""
    return s


NG_PHONE_RE = re.compile(r"(?:\+?234[\s-]?|0)[789][01]\d[\s-]?\d{3}[\s-]?\d{4}")


# ---------------------------------------------------------------- search results

def parse_count(text: str) -> int | None:
    """'12.5K' -> 12500, '1,234' -> 1234, '1.2M' -> 1200000."""
    m = re.match(r"^\s*([\d.,]+)\s*([kKmM]?)", text or "")
    if not m:
        return None
    num = m[1].replace(",", "")
    try:
        value = float(num)
    except ValueError:
        return None
    mult = {"k": 1_000, "m": 1_000_000}.get(m[2].lower(), 1)
    return int(round(value * mult))


def followers_from_snippet(text: str) -> int | None:
    m = re.search(r"([\d.,]+\s*[kKmM]?)\s+followers", text or "", re.I)
    return parse_count(m[1]) if m else None


def name_from_title(title: str) -> str:
    t = clean_text(title)
    if not t:
        return ""
    m = re.match(r"^(.*?)\s*\(@[\w.]+\)", t)
    if m and m[1].strip():
        return m[1].strip(" •|-–")
    m = re.match(r"^(.*?)\s+on\s+(Instagram|TikTok)\b", t, re.I)
    if m and m[1].strip():
        return m[1].strip(" •|-–\"")
    t = re.split(r"\s+[|•–—-]\s+", t)[0]
    return t.strip(" •|-–")[:120]


NIGERIAN_CITIES = {
    "lagos": "Lagos", "ikeja": "Lagos", "lekki": "Lagos", "ikoyi": "Lagos", "victoria island": "Lagos",
    "yaba": "Lagos", "surulere": "Lagos", "ajah": "Lagos", "ikorodu": "Lagos", "festac": "Lagos",
    "abuja": "FCT", "wuse": "FCT", "maitama": "FCT", "garki": "FCT", "gwarinpa": "FCT",
    "ibadan": "Oyo", "osogbo": "Osun", "oshogbo": "Osun", "ile-ife": "Osun", "ile ife": "Osun",
    "port harcourt": "Rivers", "enugu": "Enugu", "kano": "Kano", "benin city": "Edo", "benin": "Edo",
    "kaduna": "Kaduna", "abeokuta": "Ogun", "uyo": "Akwa Ibom", "calabar": "Cross River", "owerri": "Imo",
    "warri": "Delta", "asaba": "Delta", "jos": "Plateau", "ilorin": "Kwara", "akure": "Ondo",
    "onitsha": "Anambra", "awka": "Anambra", "ado-ekiti": "Ekiti", "ado ekiti": "Ekiti", "makurdi": "Benue",
    "minna": "Niger", "sokoto": "Sokoto", "maiduguri": "Borno", "yola": "Adamawa", "bauchi": "Bauchi",
    "lokoja": "Kogi", "abakaliki": "Ebonyi", "umuahia": "Abia", "aba": "Abia", "yenagoa": "Bayelsa",
    "ota": "Ogun", "sagamu": "Ogun", "ijebu ode": "Ogun", "ogbomoso": "Oyo",
}


def state_for_city(city: str) -> str:
    return NIGERIAN_CITIES.get((city or "").strip().lower(), "")
