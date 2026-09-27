"""Lead discovery. Pluggable search providers (legitimate APIs) + pasted URLs. No platform scraping:
Instagram/TikTok results come from search-engine indexes (title, URL, snippet), never from fetching the platform."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from . import normalize as N
from .config import Config
from .db import Conn, dumps, loads
from .dedupe import find_duplicates
from .signals import snippet_signals


class ProviderError(Exception):
    pass


def _http_json(url: str, method: str = "GET", headers: dict | None = None, body: dict | None = None, timeout: int = 20) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Accept": "application/json", **(headers or {})})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        raise ProviderError(f"HTTP {e.code} {detail}".strip())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"Network error: {getattr(e, 'reason', e)}")
    except ValueError:
        raise ProviderError("Provider returned invalid JSON")


class SearchProvider:
    name = "base"
    kind = "web"  # "web" (search results) or "places" (business listings)

    def search(self, query: str) -> list[dict]:
        raise NotImplementedError


class SerperProvider(SearchProvider):
    """Google results via serper.dev (https://serper.dev)."""
    name = "serper"

    def __init__(self, key: str):
        self.key = key

    def search(self, query: str) -> list[dict]:
        data = _http_json("https://google.serper.dev/search", "POST", {"X-API-KEY": self.key},
                          {"q": query, "gl": "ng", "hl": "en", "num": 20})
        return [{"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", ""),
                 "date": r.get("date")} for r in data.get("organic", []) if r.get("link")]


class BraveProvider(SearchProvider):
    """Brave Search API (https://brave.com/search/api/)."""
    name = "brave"

    def __init__(self, key: str):
        self.key = key

    def search(self, query: str) -> list[dict]:
        qs = urllib.parse.urlencode({"q": query, "country": "NG", "count": 20, "search_lang": "en"})
        data = _http_json(f"https://api.search.brave.com/res/v1/web/search?{qs}", "GET",
                          {"X-Subscription-Token": self.key})
        results = (data.get("web") or {}).get("results", [])
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", ""),
                 "date": r.get("page_age") or r.get("age")} for r in results if r.get("url")]


class PlacesProvider(SearchProvider):
    """Google Places API (New) Text Search — business listings with phone and website."""
    name = "google_places"
    kind = "places"
    FIELDS = ("places.displayName,places.formattedAddress,places.websiteUri,places.nationalPhoneNumber,"
              "places.internationalPhoneNumber,places.googleMapsUri,places.businessStatus,places.primaryTypeDisplayName,"
              "places.rating,places.userRatingCount")

    def __init__(self, key: str):
        self.key = key

    def search(self, query: str) -> list[dict]:
        data = _http_json("https://places.googleapis.com/v1/places:searchText", "POST",
                          {"X-Goog-Api-Key": self.key, "X-Goog-FieldMask": self.FIELDS},
                          {"textQuery": query, "regionCode": "NG", "pageSize": 20})
        out = []
        for p in data.get("places", []):
            if p.get("businessStatus") and p["businessStatus"] != "OPERATIONAL":
                continue
            name = (p.get("displayName") or {}).get("text", "")
            out.append({"title": name, "url": p.get("websiteUri") or p.get("googleMapsUri") or "", "snippet": p.get("formattedAddress", ""),
                        "date": None, "extra": {
                            "address": p.get("formattedAddress", ""), "website": p.get("websiteUri", ""),
                            "phone": p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber") or "",
                            "maps_url": p.get("googleMapsUri", ""), "rating": p.get("rating"),
                            "rating_count": p.get("userRatingCount"),
                            "category": (p.get("primaryTypeDisplayName") or {}).get("text", "")}})
        return out


def providers(cfg: Config) -> list[SearchProvider]:
    out: list[SearchProvider] = []
    if cfg.serper_key:
        out.append(SerperProvider(cfg.serper_key))
    elif cfg.brave_key:
        out.append(BraveProvider(cfg.brave_key))
    if cfg.places_key:
        out.append(PlacesProvider(cfg.places_key))
    return out


def provider_status(cfg: Config) -> list[dict]:
    return [
        {"name": "serper", "label": "Serper (Google results)", "configured": bool(cfg.serper_key), "env": "SERPER_API_KEY"},
        {"name": "brave", "label": "Brave Search API", "configured": bool(cfg.brave_key), "env": "BRAVE_SEARCH_API_KEY"},
        {"name": "google_places", "label": "Google Places (New)", "configured": bool(cfg.places_key), "env": "GOOGLE_PLACES_API_KEY"},
    ]


MAX_QUERIES = 6


def build_queries(location: str, industry: str, keywords: list[str], sources: list[str]) -> list[tuple[str, str]]:
    """Return [(provider_kind, query)] capped at MAX_QUERIES for cost control."""
    loc = location.strip()
    ind = industry.strip()
    kws = [k.strip() for k in keywords if k.strip()][:3] or [""]
    out: list[tuple[str, str]] = []
    for kw in kws:
        quoted = f' "{kw}"' if kw else ""
        if "instagram" in sources:
            out.append(("web", f"site:instagram.com {ind} {loc}{quoted}".strip()))
        if "tiktok" in sources:
            out.append(("web", f"site:tiktok.com {ind} {loc}{quoted}".strip()))
        if "web" in sources:
            out.append(("web", f"{ind} {loc} Nigeria{quoted}".strip()))
    if "places" in sources:
        out.append(("places", f"{ind} in {loc}, Nigeria".strip()))
    seen, uniq = set(), []
    for item in out:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq[:MAX_QUERIES]


def parse_candidate(result: dict, provider: str, query: str) -> dict | None:
    url = N.clean_url(result.get("url") or "")
    title = N.clean_text(result.get("title"), 300)
    snippet = N.clean_text(result.get("snippet"), 1200)
    extra = result.get("extra") or {}
    kind = N.classify_url(url) if url else "unknown"
    if kind == "unknown" and provider != "google_places":
        return None  # not a recognisable URL
    handle = ""
    platform = kind
    if kind == "instagram":
        handle = N.instagram_handle(url)
        path = urlparse(url).path.lower()
        if not handle:
            m = re.search(r"\(@([\w.]+)\)|@([\w.]+)\s*[•·]", title)
            handle = (m[1] or m[2]).lower() if m else ""
            platform = "instagram_post" if "/p/" in path or "/reel" in path else "instagram"
        if not handle:
            return None
    elif kind == "tiktok":
        handle = N.tiktok_handle(url)
        if not handle:
            return None
    elif kind in ("facebook", "x", "youtube", "linkedin"):
        platform = kind
    elif provider == "google_places":
        platform = "places"
    name = N.name_from_title(title) if provider != "google_places" else title
    if kind in ("instagram", "tiktok") and (not name or name.lower().startswith(("instagram", "tiktok", "#"))):
        name = N.title_case_handle(handle)
    low = (title + " " + snippet).lower()
    if platform == "website" and any(w in low for w in ("top 10", "top 20", "best ", " list of", "directory", "ranking")):
        platform = "article"  # listicles are research material, not a business
    d = N.parse_loose_date(str(result.get("date") or "")) if result.get("date") else None
    return {"provider": provider, "query": query, "title": title, "url": url, "snippet": snippet,
            "result_date": d.isoformat() if d else None, "platform": platform, "handle": handle,
            "name_guess": name[:120], "extra": extra, "snippet_signals": snippet_signals(title + " " + snippet),
            "followers": N.followers_from_snippet(snippet)}


def candidate_lead_fields(c: dict, location: str, industry: str) -> dict:
    """Map a candidate onto lead input fields (fed through leads.prepare)."""
    extra = c.get("extra") or {}
    d = {"business_name": c.get("name_guess") or "", "industry": industry, "city": location}
    p = c["platform"]
    if p in ("instagram", "instagram_post"):
        d["instagram_url"] = "@" + c["handle"]
        if c.get("followers"):
            d["followers_instagram"] = c["followers"]
            d["followers_source"] = "search snippet (approx.)"
    elif p == "tiktok":
        d["tiktok_url"] = "@" + c["handle"]
        if c.get("followers"):
            d["followers_tiktok"] = c["followers"]
            d["followers_source"] = "search snippet (approx.)"
    elif p == "places":
        if extra.get("website"):
            d["website_url"] = extra["website"]
        if extra.get("phone"):
            d["phone"] = extra["phone"]
        if extra.get("address"):
            d["address"] = extra["address"]
    elif p in ("website", "storefront"):
        d["website_url"] = c["url"]
    elif p == "link_page":
        d["link_in_bio_url"] = c["url"]
    elif p in ("facebook", "x", "youtube", "linkedin"):
        d["other_socials"] = {p: c["url"]}
    return d


def _match(conn: Conn, c: dict, location: str, industry: str, settings: dict):
    from .leads import prepare, ValidationError
    try:
        probe = prepare(candidate_lead_fields(c, location, industry), settings)
    except ValidationError:
        return None
    dups = find_duplicates(conn, probe)
    return dups[0] if dups else None


def _store_candidates(conn: Conn, run_id: int, cands: list[dict], location: str, industry: str, settings: dict) -> list[dict]:
    seen = set()
    stored = []
    for c in cands:
        key = (c["platform"], c["handle"] or N.business_domain(c["url"]) or c["url"] or c["title"].lower())
        if key in seen:
            continue
        seen.add(key)
        m = _match(conn, c, location, industry, settings)
        row = {"run_id": run_id, "provider": c["provider"], "query": c["query"], "title": c["title"], "url": c["url"],
               "snippet": c["snippet"], "result_date": c["result_date"], "platform": c["platform"], "handle": c["handle"],
               "name_guess": c["name_guess"], "extra": dumps({**(c.get("extra") or {}), "followers": c.get("followers")}),
               "snippet_signals": dumps(c["snippet_signals"]),
               "matched_lead_id": m["lead_id"] if m else None,
               "match_reason": (m["strength"] + ": " + ", ".join(m["match_on"])) if m else "",
               "status": "duplicate" if m and m["strength"] == "strong" else "new", "created_at": N.now_iso()}
        row["id"] = conn.insert("discovery_candidates", row)
        stored.append(row)
    return stored


def run_discovery(conn: Conn, params: dict, cfg: Config, settings: dict, provider_list=None) -> dict:
    location = N.clean_text(params.get("location"), 80)
    industry = N.clean_text(params.get("industry"), 80)
    keywords = params.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k for k in keywords.split(",")]
    sources = params.get("sources") or ["instagram", "tiktok", "web", "places"]
    if not location or not industry:
        raise ValueError("Location and industry are required")
    provs = provider_list if provider_list is not None else providers(cfg)
    ts = N.now_iso()
    clean_params = {"location": location, "industry": industry, "keywords": keywords, "sources": sources,
                    "min_score": params.get("min_score")}
    if not provs:
        run_id = conn.insert("discovery_runs", {"params": dumps(clean_params), "providers": "[]", "status": "no_provider",
                                                "message": "No search provider is configured. Add SERPER_API_KEY, BRAVE_SEARCH_API_KEY "
                                                           "or GOOGLE_PLACES_API_KEY — or paste profile URLs instead.",
                                                "result_count": 0, "created_at": ts})
        return get_run(conn, run_id)
    queries = build_queries(location, industry, keywords, sources)
    cands, errors, used = [], [], []
    for kind, q in queries:
        for p in provs:
            if p.kind != kind:
                continue
            used.append(p.name)
            try:
                for r in p.search(q):
                    c = parse_candidate(r, p.name, q)
                    if c:
                        cands.append(c)
            except ProviderError as e:
                errors.append(f"{p.name}: {e}")
    status = "ok" if cands else ("error" if errors else "empty")
    msg = "; ".join(errors[:3]) if errors else ("" if cands else "The search returned no business candidates.")
    run_id = conn.insert("discovery_runs", {"params": dumps(clean_params), "providers": dumps(sorted(set(used))),
                                            "status": status, "message": msg, "result_count": 0, "created_at": ts})
    stored = _store_candidates(conn, run_id, cands, location, industry, settings)
    conn.update("discovery_runs", run_id, {"result_count": len(stored)})
    return get_run(conn, run_id)


def candidates_from_urls(conn: Conn, urls: list[str], params: dict, settings: dict) -> dict:
    location = N.clean_text(params.get("location"), 80)
    industry = N.clean_text(params.get("industry"), 80)
    cands, skipped = [], []
    for raw in urls[:200]:
        u = N.clean_url(raw)
        if not u:
            continue
        if u.startswith("@"):
            u = N.instagram_url(N.instagram_handle(u))
        c = parse_candidate({"url": u, "title": "", "snippet": ""}, "pasted", "")
        if not c:
            skipped.append(raw)
            continue
        if not c["name_guess"]:
            c["name_guess"] = N.title_case_handle(c["handle"]) if c["handle"] else (N.business_domain(u) or u).split(".")[0].title()
        cands.append(c)
    run_id = conn.insert("discovery_runs", {"params": dumps({"location": location, "industry": industry, "mode": "pasted"}),
                                            "providers": dumps(["pasted"]), "status": "ok" if cands else "empty",
                                            "message": (f"Skipped {len(skipped)} unrecognised URL(s)" if skipped else ""),
                                            "result_count": 0, "created_at": N.now_iso()})
    stored = _store_candidates(conn, run_id, cands, location, industry, settings)
    conn.update("discovery_runs", run_id, {"result_count": len(stored)})
    return get_run(conn, run_id)


def get_run(conn: Conn, run_id: int) -> dict:
    run = conn.one("SELECT * FROM discovery_runs WHERE id = ?", [run_id])
    if not run:
        raise KeyError(run_id)
    run["params"] = loads(run["params"], {})
    run["providers"] = loads(run["providers"], [])
    cands = conn.all("SELECT * FROM discovery_candidates WHERE run_id = ? ORDER BY id", [run_id])
    for c in cands:
        c["extra"] = loads(c["extra"], {})
        c["snippet_signals"] = loads(c["snippet_signals"], [])
    run["candidates"] = cands
    return run


def recent_runs(conn: Conn, limit: int = 10) -> list[dict]:
    rows = conn.all("SELECT id, params, providers, status, message, result_count, created_at FROM discovery_runs ORDER BY id DESC LIMIT ?", [limit])
    for r in rows:
        r["params"] = loads(r["params"], {})
        r["providers"] = loads(r["providers"], [])
    return rows
