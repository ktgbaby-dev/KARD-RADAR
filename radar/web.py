"""HTTP plumbing: routing, JSON I/O, auth gate, CSRF check, security headers, static files."""
import json
import mimetypes
import re
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import auth
from .config import ROOT, Config
from .db import Database

STATIC = ROOT / "static"
MAX_BODY = 8 * 1024 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


class Request:
    def __init__(self, handler: "Handler", method: str, path: str, query: dict, params: dict, body):
        self.handler = handler
        self.method = method
        self.path = path
        self.query = query
        self.params = params
        self.body = body
        self.cfg: Config = handler.server.cfg
        self.db: Database = handler.server.db
        self.headers = handler.headers

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


class Handler(BaseHTTPRequestHandler):
    server_version = "KardRadar"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # concise access log, never bodies
        if self.server.quiet:
            return
        super().log_message(fmt, *args)

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def _send(self, resp: Response):
        body = resp.body
        if resp.content_type == "application/json":
            body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            ctype = resp.content_type
            if isinstance(body, str):
                body = body.encode("utf-8")
        body = body or b""
        self.send_response(resp.status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authed(self) -> bool:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get(auth.COOKIE)
        return auth.verify(token.value if token else None, self.server.cfg.session_secret)

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            if method in ("GET", "HEAD"):
                return self._static(path)
            return self._send(Response(405, {"error": "Method not allowed"}))
        try:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                self.close_connection = True
                raise ApiError(413, "Request body too large")
            raw = self.rfile.read(length) if length else b""  # always drain the body (keep-alive safety)
            for m, rx, fn, need_auth in ROUTES:
                if m != method:
                    continue
                match = rx.match(path)
                if not match:
                    continue
                if need_auth and not self._authed():
                    raise ApiError(401, "Please sign in")
                if method != "GET" and self.headers.get("X-Requested-With") != "KardRadar":
                    raise ApiError(403, "Missing request header")
                body = None
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        raise ApiError(400, "Body must be JSON")
                    if not isinstance(body, dict):
                        raise ApiError(400, "Body must be a JSON object")
                req = Request(self, method, path, parse_qs(parsed.query), match.groupdict(), body or {})
                result = fn(req)
                return self._send(result if isinstance(result, Response) else Response(200, result))
            raise ApiError(404, "Not found")
        except ApiError as e:
            return self._send(Response(e.status, {"error": e.message, **e.extra}))
        except Exception:  # never leak internals to the client
            traceback.print_exc()
            return self._send(Response(500, {"error": "Internal error — see server log"}))

    def _static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            target = STATIC / "index.html"  # SPA fallback
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        if target.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        self._send(Response(200, target.read_bytes(), ctype))

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")


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
