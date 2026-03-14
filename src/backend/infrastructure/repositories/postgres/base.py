"""Base Postgres repository — connection handling and migration runner."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import psycopg2

from backend.config import ADMIN_TELEGRAM_IDS, DATABASE_URL

logger = logging.getLogger(__name__)

_OP_RE = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|WITH)", re.IGNORECASE)
_TABLE_RE = re.compile(
    r"(?:FROM|INTO|UPDATE|JOIN)\s+(\w+)", re.IGNORECASE,
)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class _LoggingCursor:
    """Thin wrapper that logs operation type, table, and duration."""

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        op = m.group(1).upper() if (m := _OP_RE.match(sql)) else "?"
        table = m.group(1) if (m := _TABLE_RE.search(sql)) else "?"
        t0 = time.monotonic()
        self._cur.execute(sql, params)
        ms = (time.monotonic() - t0) * 1000
        rows = self._cur.rowcount if self._cur.rowcount >= 0 else 0
        logger.debug("db %s %s → %d rows (%.1fms)", op, table, rows, ms)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._cur.close()

    def __getattr__(self, name):
        return getattr(self._cur, name)

    def __iter__(self):
        return iter(self._cur)


class BasePostgresRepo:

    def __init__(self):
        self._conn = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(DATABASE_URL)
            self._conn.autocommit = True
        return self._conn

    def _cursor(self):
        return _LoggingCursor(self._get_conn().cursor())

    def init_schema(self):
        self._run_migrations()
        self._seed_bindings()

    def _run_migrations(self):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

        # Bootstrap: existing DB already has all tables from the old monolithic SQL.
        # Mark 001_initial as applied without running it.
        if not applied:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'units_of_knowledge'"
                )
                if cur.fetchone():
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES ('001_initial')"
                    )
                    applied.add("001_initial")
                    logger.info("Bootstrapped: marked 001_initial as applied")

        migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        for f in migration_files:
            version = f.stem  # e.g. "001_initial"
            if version in applied:
                continue
            logger.info("Applying migration %s", version)
            sql = f.read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            logger.info("Migration %s applied", version)

    def _seed_bindings(self):
        conn = self._get_conn()
        with conn.cursor() as cur:
            for admin_id in ADMIN_TELEGRAM_IDS:
                cur.execute(
                    "INSERT INTO environment_bindings (chat_id, environment) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (admin_id, "dm"),
                )
                cur.execute(
                    "INSERT INTO users (name, role, telegram_id) VALUES (%s, %s, %s) "
                    "ON CONFLICT (telegram_id) DO UPDATE SET role = 'admin'",
                    ("admin", "admin", admin_id),
                )

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None
