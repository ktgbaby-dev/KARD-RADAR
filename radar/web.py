"""HTTP plumbing: routing, JSON I/O, auth gate, CSRF check, security headers, static files.

`dispatch()` is framework-neutral. Two adapters call it:
  - `Handler` / `make_server()`  — the built-in threaded server used locally (`python server.py`)
  - `radar.wsgi.app`             — a WSGI app for Vercel and any WSGI host (gunicorn, waitress…)
"""
import json
import mimetypes
import re
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import auth
from .config import ROOT, Config
from .db import Database

STATIC = ROOT / "static"
MAX_BODY = 8 * 1024 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", CSP),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
]


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


class Request:
    def __init__(self, cfg: Config, db: Database, method: str, path: str, query: dict, params: dict, body,
                 headers, client_ip: str, authed: bool):
        self.cfg = cfg
        self.db = db
        self.method = method
        self.path = path
        self.query = query
        self.params = params
        self.body = body
        self.headers = headers
        self.client_ip = client_ip
        self.authed = authed

    def arg(self, name, default=None):
        v = self.query.get(name)
        return v[0] if v else default


class Response:
    def __init__(self, status=200, body=None, content_type="application/json", headers=None):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.headers = headers or {}


ROUTES: list[tuple[str, re.Pattern, callable, bool]] = []


def route(method: str, pattern: str, auth_required: bool = True):
    rx = re.compile("^" + re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", pattern) + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn, auth_required))
        return fn
    return deco


def _authed(cookie_header: str, cfg: Config) -> bool:
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header or "")
    except Exception:  # malformed cookie header
        return False
    token = cookie.get(auth.COOKIE)
    return auth.verify(token.value if token else None, cfg.session_secret)


def _serialize(resp: Response, is_api: bool, head: bool) -> tuple[int, list[tuple[str, str]], bytes]:
    body = resp.body
    if resp.content_type == "application/json":
        body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        ctype = "application/json; charset=utf-8"
    else:
        ctype = resp.content_type
        if isinstance(body, str):
            body = body.encode("utf-8")
    body = body or b""
    headers = [("Content-Type", ctype), ("Content-Length", str(len(body))),
               ("Cache-Control", "no-store" if is_api else "no-cache")]
    headers += list(resp.headers.items()) + SECURITY_HEADERS
    return resp.status, headers, (b"" if head else body)


def _static(path: str) -> Response:
    if path in ("", "/"):
        path = "/index.html"
    elif path == "/favicon.ico":
        path = "/img/favicon.svg"
    target = (STATIC / path.lstrip("/")).resolve()
    if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
        target = STATIC / "index.html"  # SPA fallback
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if target.suffix == ".js":
        ctype = "text/javascript"
    if ctype.startswith("text/") or ctype == "image/svg+xml":
        ctype += "; charset=utf-8"
    return Response(200, target.read_bytes(), ctype)


def dispatch(cfg: Config, db: Database | None, method: str, raw_path: str, headers, body: bytes,
             client_ip: str, db_error: str = "", too_large: bool = False) -> tuple[int, list[tuple[str, str]], bytes]:
    """Handle one request. `headers` needs a case-insensitive .get(); returns (status, headers, body)."""
    parsed = urlparse(raw_path)
    path = parsed.path
    head = method == "HEAD"
    if head:
        method = "GET"
    is_api = path.startswith("/api/")
    if not is_api:
        if method != "GET":
            return _serialize(Response(405, {"error": "Method not allowed"}), False, head)
        return _serialize(_static(path), False, head)
    try:
        if too_large or len(body) > MAX_BODY:
            raise ApiError(413, "Request body too large")
        for m, rx, fn, need_auth in ROUTES:
            if m != method:
                continue
            match = rx.match(path)
            if not match:
                continue
            if db is None:
                raise ApiError(503, db_error or "Database is not configured")
            authed = _authed(headers.get("Cookie", ""), cfg)
            if need_auth and not authed:
                raise ApiError(401, "Please sign in")
            if method != "GET" and headers.get("X-Requested-With") != "KardRadar":
                raise ApiError(403, "Missing request header")
            data = None
            if body:
                try:
                    data = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise ApiError(400, "Body must be JSON")
                if not isinstance(data, dict):
                    raise ApiError(400, "Body must be a JSON object")
            req = Request(cfg, db, method, path, parse_qs(parsed.query), match.groupdict(), data or {}, headers,
                          client_ip, authed)
            result = fn(req)
            return _serialize(result if isinstance(result, Response) else Response(200, result), True, head)
        raise ApiError(404, "Not found")
    except ApiError as e:
        return _serialize(Response(e.status, {"error": e.message, **e.extra}), True, head)
    except Exception:  # never leak internals to the client
        traceback.print_exc()
        return _serialize(Response(500, {"error": "Internal error — see server log"}), True, head)


# ------------------------------------------------------------------ built-in server (local use)

class Handler(BaseHTTPRequestHandler):
    server_version = "KardRadar"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # concise access log, never bodies
        if self.server.quiet:
            return
        super().log_message(fmt, *args)

    def _run(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        too_large = length > MAX_BODY
        if too_large:
            self.close_connection = True  # don't read an oversized body; drop the connection after replying
            body = b""
        else:
            body = self.rfile.read(length) if length else b""  # always drain (keep-alive safety)
        status, headers, payload = dispatch(self.server.cfg, self.server.db, self.command, self.path, self.headers,
                                            body, self.client_address[0], too_large=too_large)
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = _run


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, cfg: Config, db: Database, quiet: bool = False):
        super().__init__(addr, Handler)
        self.cfg = cfg
        self.db = db
        self.quiet = quiet


def make_server(host: str, port: int, cfg: Config, db: Database, quiet: bool = False) -> Server:
    from . import api  # noqa: F401  (registers routes)
    return Server((host, port), cfg, db, quiet)
