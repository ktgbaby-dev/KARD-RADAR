"""Environment configuration. Secrets are read from the process environment or a local .env file
(never from the client, never written to logs)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Real environment variables win over .env values.
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def find_database_url() -> str:
    """DATABASE_URL / POSTGRES_URL, or the same names with the custom prefix Vercel's Storage integrations allow
    (e.g. STORAGE_DATABASE_URL). Pooled URLs are preferred; Prisma-style URLs are skipped (psycopg rejects them)."""
    for key in ("DATABASE_URL", "POSTGRES_URL"):
        if env(key).startswith(("postgres://", "postgresql://")):
            return env(key)
    for suffix in ("_DATABASE_URL", "_POSTGRES_URL"):
        for key in sorted(os.environ):
            if key.endswith(suffix) and env(key).startswith(("postgres://", "postgresql://")):
                return env(key)
    return ""


class Config:
    def __init__(self) -> None:
        # Vercel sets VERCEL=1. Its disk is temporary, so SQLite is refused there (see radar/wsgi.py).
        self.on_vercel = env("VERCEL") == "1"
        # DATABASE_URL, or the names Vercel's Neon / Supabase / Postgres integrations inject.
        self.database_url = find_database_url()
        self.db_path = env("KARD_DB_PATH", str(ROOT / "data" / "kard_radar.db"))
        self.admin_password = env("ADMIN_PASSWORD")
        self.session_secret = env("SESSION_SECRET")
        self.secure_cookies = env("SECURE_COOKIES", "1" if self.on_vercel else "0") == "1"
        self.anthropic_key_set = bool(env("ANTHROPIC_API_KEY"))
        self.anthropic_model = env("ANTHROPIC_MODEL", "claude-opus-5")
        self.ai_effort = env("AI_EFFORT", "medium")
        self.serper_key = env("SERPER_API_KEY")
        self.brave_key = env("BRAVE_SEARCH_API_KEY")
        self.places_key = env("GOOGLE_PLACES_API_KEY")
        self.fetch_user_agent = env(
            "FETCH_USER_AGENT", "KardRadar/1.0 (+internal research tool by Kal's Digital)")
        # Test-only escape hatch so the test-suite can fetch fixtures from 127.0.0.1.
        self.allow_private_fetch = env("KARD_ALLOW_PRIVATE_FETCH", "0") == "1"


def get_config() -> Config:
    return Config()
