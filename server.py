"""Kard Radar server.

    python server.py --init          # create .env with a generated admin password + session secret
    python server.py                 # serve on http://127.0.0.1:5610
    python server.py --host 0.0.0.0 --port $PORT   # production (behind HTTPS; set SECURE_COOKIES=1)
"""
import argparse
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def init_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        text = env.read_text(encoding="utf-8")
        if re.search(r"^ADMIN_PASSWORD=.+", text, re.M) and re.search(r"^SESSION_SECRET=.+", text, re.M):
            print(".env already exists with ADMIN_PASSWORD and SESSION_SECRET - nothing changed.")
            return
    else:
        text = (ROOT / ".env.example").read_text(encoding="utf-8") if (ROOT / ".env.example").exists() else ""
    lines = [l for l in text.splitlines() if not l.startswith(("ADMIN_PASSWORD=", "SESSION_SECRET="))]
    lines += [f"ADMIN_PASSWORD={secrets.token_urlsafe(12)}", f"SESSION_SECRET={secrets.token_hex(32)}"]
    env.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    print(f"Wrote {env} - your admin password is the ADMIN_PASSWORD line in that file.")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Kard Radar — lead intelligence & outreach")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5610")))
    ap.add_argument("--db", help="SQLite database path (default data/kard_radar.db)")
    ap.add_argument("--init", action="store_true", help="create .env with generated credentials and exit")
    ap.add_argument("--quiet", action="store_true", help="no access log")
    args = ap.parse_args()
    if args.init:
        init_env()
        return
    if args.db:
        os.environ["KARD_DB_PATH"] = str(Path(args.db).resolve())
    sys.path.insert(0, str(ROOT))
    from radar.config import get_config
    from radar.db import Database
    from radar.web import make_server

    cfg = get_config()
    if not cfg.admin_password or not cfg.session_secret:
        print("ADMIN_PASSWORD and SESSION_SECRET must be set. Run:  python server.py --init", file=sys.stderr)
        sys.exit(1)
    if len(cfg.session_secret) < 32:
        print("SESSION_SECRET should be at least 32 characters.", file=sys.stderr)
        sys.exit(1)
    db = Database(cfg)
    db.connect().close()  # create schema
    srv = make_server(args.host, args.port, cfg, db, quiet=args.quiet)
    where = "PostgreSQL" if db.dialect == "pg" else db.path
    print(f"Kard Radar running on http://{args.host}:{args.port}  (database: {where})")
    print(f"AI analysis: {'on - ' + cfg.anthropic_model if cfg.anthropic_key_set else 'off (ANTHROPIC_API_KEY not set)'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
