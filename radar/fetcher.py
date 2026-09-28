"""Polite, SSRF-guarded fetcher for public business websites and link-in-bio pages.

- http/https only; private, loopback, link-local and reserved IPs are refused (checked on every redirect)
- Instagram, TikTok, Facebook, X, Threads and LinkedIn are never fetched (platform terms)
- robots.txt is honoured; responses are size-capped, time-limited and cached in `fetch_cache`
"""
import ipaddress
import socket
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from .config import Config
from .db import Conn
from .normalize import host_of, now_iso

BLOCKED_PLATFORMS = ("instagram.com", "tiktok.com", "facebook.com", "fb.com", "x.com", "twitter.com",
                     "threads.net", "linkedin.com", "snapchat.com")
MAX_BYTES = 1_500_000
MAX_STORED_CHARS = 400_000
TIMEOUT = 10
MAX_REDIRECTS = 5
_robots_cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}


class FetchResult(dict):
    """dict with attribute access: url, final_url, status, content_type, body, error, from_cache, elapsed_ms, fetched_at"""
    __getattr__ = dict.get


def is_platform_blocked(url: str) -> bool:
    host = host_of(url)
    return any(host == p or host.endswith("." + p) for p in BLOCKED_PLATFORMS)


def _check_host(url: str, cfg: Config) -> str | None:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return "Only http(s) URLs can be fetched"
    if not p.hostname:
        return "URL has no host"
    if is_platform_blocked(url):
        return "Social platform pages are not fetched — add a social snapshot or use an approved API"
    if cfg.allow_private_fetch:
        return None
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        return "Domain does not resolve"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return "Refusing to fetch a private or local network address"
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _raw_get(url: str, cfg: Config, max_bytes: int = MAX_BYTES) -> FetchResult:
    """GET with manual redirect handling so every hop is re-validated."""
    started = time.monotonic()
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        problem = _check_host(current, cfg)
        if problem:
            return FetchResult(url=url, final_url=current, status=None, error=problem, body="", content_type="",
                               elapsed_ms=int((time.monotonic() - started) * 1000))
        req = urllib.request.Request(current, headers={
            "User-Agent": cfg.fetch_user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-NG,en;q=0.9",
        })
        try:
            resp = _opener.open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                current = urljoin(current, e.headers["Location"])
                continue
            return FetchResult(url=url, final_url=current, status=e.code, error=f"HTTP {e.code}", body="",
                               content_type=e.headers.get("Content-Type", "") if e.headers else "",
                               elapsed_ms=int((time.monotonic() - started) * 1000))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            return FetchResult(url=url, final_url=current, status=None, error=f"Could not connect ({reason})"[:200],
                               body="", content_type="", elapsed_ms=int((time.monotonic() - started) * 1000))
        with resp:
            ctype = resp.headers.get("Content-Type", "")
            data = resp.read(max_bytes + 1)
            status = resp.status
        truncated = len(data) > max_bytes
        data = data[:max_bytes]
        body = ""
        if any(t in ctype.lower() for t in ("html", "text/plain", "xml")) or not ctype:
            charset = "utf-8"
            if "charset=" in ctype.lower():
                charset = ctype.lower().split("charset=")[-1].split(";")[0].strip() or "utf-8"
            try:
                body = data.decode(charset, errors="replace")
            except LookupError:
                body = data.decode("utf-8", errors="replace")
        return FetchResult(url=url, final_url=current, status=status, content_type=ctype, body=body.replace("\x00", "")[:MAX_STORED_CHARS],
                           error="" if not truncated else "Response truncated at size limit",
                           elapsed_ms=int((time.monotonic() - started) * 1000))
    return FetchResult(url=url, final_url=current, status=None, error="Too many redirects", body="", content_type="",
                       elapsed_ms=int((time.monotonic() - started) * 1000))


def robots_allows(url: str, cfg: Config) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    cached = _robots_cache.get(base)
    if cached and time.time() - cached[0] < 3600:
        rp = cached[1]
    else:
        res = _raw_get(base + "/robots.txt", cfg, max_bytes=200_000)
        rp = None
        if res.status == 200 and res.body:
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(res.body.splitlines())
        _robots_cache[base] = (time.time(), rp)
    if rp is None:  # no robots.txt (or unreachable) -> allowed
        return True
    return rp.can_fetch(cfg.fetch_user_agent, url)


def fetch(conn: Conn, url: str, cfg: Config, refresh: bool = False, cache_days: int = 7) -> FetchResult:
    if not refresh and cache_days > 0:
        row = conn.one("SELECT * FROM fetch_cache WHERE url = ?", [url])
        if row:
            fetched = datetime.fromisoformat(row["fetched_at"])
            if datetime.now(timezone.utc) - fetched < timedelta(days=cache_days):
                return FetchResult(url=url, final_url=row["final_url"], status=row["status"],
                                   content_type=row["content_type"], body=row["body"], error=row["error"],
                                   elapsed_ms=row["elapsed_ms"], fetched_at=row["fetched_at"], from_cache=True)
    problem = _check_host(url, cfg)
    if problem:
        return FetchResult(url=url, final_url=url, status=None, error=problem, body="", content_type="",
                           fetched_at=now_iso(), from_cache=False, blocked=True)
    if not robots_allows(url, cfg):
        res = FetchResult(url=url, final_url=url, status=None, error="Blocked by the site's robots.txt", body="",
                          content_type="", elapsed_ms=0)
    else:
        res = _raw_get(url, cfg)
    res["fetched_at"] = now_iso()
    res["from_cache"] = False
    conn.run("INSERT INTO fetch_cache (url, final_url, status, content_type, body, error, elapsed_ms, fetched_at) "
             "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(url) DO UPDATE SET final_url = excluded.final_url, "
             "status = excluded.status, content_type = excluded.content_type, body = excluded.body, "
             "error = excluded.error, elapsed_ms = excluded.elapsed_ms, fetched_at = excluded.fetched_at",
             [url, res.final_url or "", res.status, res.content_type or "", res.body or "", res.error or "",
              res.elapsed_ms or 0, res["fetched_at"]])
    return res
