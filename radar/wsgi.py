"""WSGI entrypoint — used by Vercel (see pyproject.toml [tool.vercel]) and any WSGI server.

    Vercel:   entrypoint = "radar.wsgi:app"
    Other:    waitress-serve radar.wsgi:app   /   gunicorn radar.wsgi:app

Configuration problems (missing secrets, SQLite on Vercel, unreachable database) are reported on the
login screen and in the function log instead of crashing, so a misconfigured deploy explains itself.
"""
import sys
import threading
import traceback
from http import HTTPStatus

from . import api  # noqa: F401  (registers routes)
from .config import get_config
from .db import Database
from .web import MAX_BODY, dispatch

_lock = threading.Lock()
_state: dict = {}


def _setup():
    with _lock:
        if _state:
            return _state
        cfg = get_config()
        db, error = None, ""
        if not cfg.admin_password or not cfg.session_secret:
            error = "Server is not configured: set ADMIN_PASSWORD and SESSION_SECRET environment variables."
        elif len(cfg.session_secret) < 32:
            error = "SESSION_SECRET must be at least 32 characters."
        elif cfg.on_vercel and not cfg.database_url:
            error = ("No database configured. Vercel's disk is temporary, so SQLite would lose your leads. "
                     "Add a Postgres database (e.g. Neon from the Vercel Marketplace) and set DATABASE_URL.")
        else:
            try:
                db = Database(cfg)
                db.connect().close()  # creates the schema on first run
            except Exception as e:  # report the class, never the URL (it contains the password)
                traceback.print_exc()
                db = None
                error = f"Could not connect to the database ({type(e).__name__}). Check DATABASE_URL."
        if error:
            print(f"[kard-radar] {error}", file=sys.stderr)
        _state.update(cfg=cfg, db=db, error=error)
        return _state


class _EnvironHeaders:
    """Case-insensitive header lookup over a WSGI environ."""

    def __init__(self, environ):
        self.environ = environ

    def get(self, name, default=None):
        key = name.upper().replace("-", "_")
        if key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            return self.environ.get(key, default)
        return self.environ.get("HTTP_" + key, default)


def _client_ip(environ, trust_proxy: bool) -> str:
    if trust_proxy:  # on Vercel the edge sets these; elsewhere they could be spoofed
        fwd = environ.get("HTTP_X_REAL_IP") or environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        if fwd:
            return fwd
    return environ.get("REMOTE_ADDR", "")


def app(environ, start_response):
    st = _setup()
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/") or "/"
    try:  # WSGI decodes the path as latin-1; restore UTF-8
        path = path.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    qs = environ.get("QUERY_STRING", "")
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    too_large = length > MAX_BODY
    body = environ["wsgi.input"].read(length) if length and not too_large else b""
    status, headers, payload = dispatch(
        st["cfg"], st["db"], method, path + ("?" + qs if qs else ""), _EnvironHeaders(environ), body,
        _client_ip(environ, st["cfg"].on_vercel), db_error=st["error"], too_large=too_large)
    start_response(f"{status} {HTTPStatus(status).phrase}", headers)
    return [payload]
