"""Read-only SQL gateways for external and local DBs."""

from __future__ import annotations

import logging
import re

import psycopg2
from sshtunnel import SSHTunnelForwarder

logger = logging.getLogger(__name__)

_SELECT_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


class LocalQueryGateway:
    """Execute read-only SQL against a local postgres (no SSH tunnel)."""

    def __init__(self, dsn: str, name: str = "local"):
        self._dsn = dsn
        self._name = name
        self._conn = None

    @property
    def available(self) -> bool:
        return bool(self._dsn)

    def _ensure_conn(self):
        if self._conn and not self._conn.closed:
            return
        self._conn = psycopg2.connect(self._dsn)
        self._conn.autocommit = True

    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        if not _SELECT_RE.match(sql):
            raise ValueError("Only SELECT queries are allowed")
        self._ensure_conn()
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception:
            self._conn = None
            raise

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None


class QueryGateway:
    """Execute read-only SQL against an external postgres via SSH tunnel."""

    def __init__(
        self,
        ssh_host: str,
        ssh_user: str,
        ssh_key_path: str,
        db_host: str,
        db_port: int,
        db_name: str,
        db_user: str,
        db_pass: str,
        name: str = "",
    ):
        self._ssh_host = ssh_host
        self._ssh_user = ssh_user
        self._ssh_key_path = ssh_key_path
        self._db_host = db_host
        self._db_port = db_port
        self._db_name = db_name
        self._db_user = db_user
        self._db_pass = db_pass
        self._name = name or db_name
        self._tunnel: SSHTunnelForwarder | None = None
        self._conn = None

    @property
    def available(self) -> bool:
        return bool(self._ssh_host and self._db_name)

    def _ensure_tunnel(self):
        if self._tunnel and self._tunnel.is_active:
            return
        if self._tunnel:
            try:
                self._tunnel.close()
            except Exception:
                pass
        self._tunnel = SSHTunnelForwarder(
            self._ssh_host,
            ssh_username=self._ssh_user,
            ssh_pkey=self._ssh_key_path,
            remote_bind_address=(self._db_host, self._db_port),
        )
        self._tunnel.start()
        logger.info("SSH tunnel to %s opened (local port %d)", self._name, self._tunnel.local_bind_port)

    def _ensure_conn(self):
        self._ensure_tunnel()
        if self._conn and not self._conn.closed:
            return
        self._conn = psycopg2.connect(
            host="127.0.0.1",
            port=self._tunnel.local_bind_port,
            dbname=self._db_name,
            user=self._db_user,
            password=self._db_pass,
        )
        self._conn.autocommit = True

    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        """Run a SELECT query and return rows as dicts. Rejects non-SELECT."""
        if not _SELECT_RE.match(sql):
            raise ValueError("Only SELECT queries are allowed")
        self._ensure_conn()
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception:
            # Connection may be stale — reset and re-raise
            self._conn = None
            raise

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None
        if self._tunnel:
            try:
                self._tunnel.close()
            except Exception:
                pass
            self._tunnel = None
