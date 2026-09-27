"""Single-admin authentication: password from ADMIN_PASSWORD, HMAC-signed session cookie, login throttling."""
import hashlib
import hmac
import secrets
import threading
import time

COOKIE = "kr_session"
SESSION_SECONDS = 7 * 24 * 3600
_failures: dict[str, list[float]] = {}
_lock = threading.Lock()
MAX_FAILURES = 5
WINDOW = 600


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue(secret: str) -> str:
    expiry = int(time.time()) + SESSION_SECONDS
    payload = f"{expiry}.{secrets.token_hex(8)}"
    return f"{payload}.{_sign(payload, secret)}"


def verify(token: str | None, secret: str) -> bool:
    if not token or token.count(".") != 2:
        return False
    expiry, nonce, sig = token.split(".")
    if not hmac.compare_digest(sig, _sign(f"{expiry}.{nonce}", secret)):
        return False
    try:
        return int(expiry) > time.time()
    except ValueError:
        return False


def throttled(ip: str) -> bool:
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(ip, []) if now - t < WINDOW]
        _failures[ip] = recent
        return len(recent) >= MAX_FAILURES


def check_password(ip: str, supplied: str, expected: str) -> bool:
    ok = bool(expected) and hmac.compare_digest((supplied or "").encode(), expected.encode())
    if not ok:
        with _lock:
            _failures.setdefault(ip, []).append(time.time())
    else:
        with _lock:
            _failures.pop(ip, None)
    return ok


def cookie_header(token: str, secure: bool, clear: bool = False) -> str:
    parts = [f"{COOKIE}={'' if clear else token}", "Path=/", "HttpOnly", "SameSite=Strict",
             f"Max-Age={0 if clear else SESSION_SECONDS}"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)
