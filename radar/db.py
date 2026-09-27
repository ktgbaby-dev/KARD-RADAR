"""Database access. SQLite by default; PostgreSQL when DATABASE_URL is set (requires `psycopg`).

All SQL in the app uses `?` placeholders, ISO text timestamps and TEXT JSON so the same statements run on both.
The PostgreSQL path is written for portability but is not exercised by the test-suite in this environment."""
import json
import sqlite3
import threading
from pathlib import Path

from .config import ROOT, Config

_SCHEMA = (ROOT / "radar" / "schema.sql").read_text(encoding="utf-8")
_init_lock = threading.Lock()


class Conn:
    def __init__(self, raw, dialect: str):
        self.raw = raw
        self.dialect = dialect

    # -- helpers
    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "pg" else sql

    def _cursor(self):
        return self.raw.cursor()

    def all(self, sql: str, params=()) -> list[dict]:
        cur = self._cursor()
        cur.execute(self._sql(sql), tuple(params))
        rows = cur.fetchall()
        if self.dialect == "sqlite":
            return [dict(r) for r in rows]
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    def one(self, sql: str, params=()) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params=()):
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def run(self, sql: str, params=()) -> int:
        cur = self._cursor()
        cur.execute(self._sql(sql), tuple(params))
        return cur.rowcount

    def insert(self, table: str, data: dict) -> int:
        cols = list(data.keys())
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) RETURNING id"
        row = self.one(sql, [data[c] for c in cols])
        return int(row["id"])

    def update(self, table: str, row_id: int, data: dict, key: str = "id") -> None:
        if not data:
            return
        sets = ", ".join(f"{c} = ?" for c in data)
        self.run(f"UPDATE {table} SET {sets} WHERE {key} = ?", [*data.values(), row_id])

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()


class Database:
    def __init__(self, cfg: Config, db_path: str | None = None):
        self.cfg = cfg
        url = cfg.database_url
        self.dialect = "pg" if url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self.path = db_path or cfg.db_path
        self._initialized = False

    def connect(self) -> Conn:
        if self.dialect == "pg":
            import psycopg  # noqa: optional dependency, only needed for PostgreSQL
            raw = psycopg.connect(self.cfg.database_url)
            conn = Conn(raw, "pg")
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            raw = sqlite3.connect(self.path, timeout=15)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA busy_timeout = 15000")
            conn = Conn(raw, "sqlite")
        if not self._initialized:
            with _init_lock:
                if not self._initialized:
                    self._init_schema(conn)
                    self._initialized = True
        return conn

    def _init_schema(self, conn: Conn) -> None:
        if self.dialect == "sqlite":
            conn.raw.execute("PRAGMA journal_mode = WAL")
            conn.raw.executescript(_SCHEMA.replace("{PK}", "INTEGER PRIMARY KEY AUTOINCREMENT"))
            _migrate_sqlite(conn)
        else:
            sql = _SCHEMA.replace("{PK}", "BIGSERIAL PRIMARY KEY")
            cur = conn.raw.cursor()
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                if stmt.startswith("--") and "\n" not in stmt:
                    continue
                cur.execute(stmt)
            for table, cols in _ADDED_COLUMNS.items():
                for name, ddl in cols:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}")
        conn.commit()


# Columns added after the first schema version. Each entry is applied only if missing.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    # "leads": [("new_column", "TEXT DEFAULT ''")],
}


def _migrate_sqlite(conn: Conn) -> None:
    for table, cols in _ADDED_COLUMNS.items():
        existing = {r["name"] for r in conn.all(f"PRAGMA table_info({table})")}
        for name, ddl in cols:
            if name not in existing:
                conn.raw.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value, default=None):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
