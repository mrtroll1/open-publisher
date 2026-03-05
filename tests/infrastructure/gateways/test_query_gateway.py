"""Tests for QueryGateway — read-only SQL execution via SSH tunnel."""

import pytest
from unittest.mock import patch, MagicMock

from backend.infrastructure.gateways.query_gateway import QueryGateway


def _make_gw(**overrides):
    defaults = dict(
        ssh_host="host", ssh_user="user", ssh_key_path="/key",
        db_host="127.0.0.1", db_port=5432, db_name="testdb",
        db_user="ro", db_pass="pass", name="test",
    )
    defaults.update(overrides)
    return QueryGateway(**defaults)


class TestAvailable:
    def test_available_when_configured(self):
        gw = _make_gw()
        assert gw.available is True

    def test_not_available_when_ssh_host_empty(self):
        gw = _make_gw(ssh_host="")
        assert gw.available is False

    def test_not_available_when_db_name_empty(self):
        gw = _make_gw(db_name="")
        assert gw.available is False


class TestSelectGuard:
    def test_rejects_insert(self):
        gw = _make_gw()
        with pytest.raises(ValueError, match="Only SELECT"):
            gw.execute("INSERT INTO t VALUES (1)")

    def test_rejects_update(self):
        gw = _make_gw()
        with pytest.raises(ValueError, match="Only SELECT"):
            gw.execute("UPDATE t SET x = 1")

    def test_rejects_delete(self):
        gw = _make_gw()
        with pytest.raises(ValueError, match="Only SELECT"):
            gw.execute("DELETE FROM t")

    def test_rejects_drop(self):
        gw = _make_gw()
        with pytest.raises(ValueError, match="Only SELECT"):
            gw.execute("DROP TABLE t")

    def test_allows_select(self):
        gw = _make_gw()
        with patch.object(gw, "_ensure_conn"):
            mock_cur = MagicMock()
            mock_cur.description = [("id",), ("name",)]
            mock_cur.fetchall.return_value = [(1, "a")]
            mock_conn = MagicMock()
            mock_conn.closed = False
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            gw._conn = mock_conn
            rows = gw.execute("SELECT id, name FROM t")
            assert rows == [{"id": 1, "name": "a"}]

    def test_allows_with_cte(self):
        gw = _make_gw()
        with patch.object(gw, "_ensure_conn"):
            mock_cur = MagicMock()
            mock_cur.description = [("cnt",)]
            mock_cur.fetchall.return_value = [(5,)]
            mock_conn = MagicMock()
            mock_conn.closed = False
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            gw._conn = mock_conn
            rows = gw.execute("WITH cte AS (SELECT 1) SELECT count(*) as cnt FROM cte")
            assert rows == [{"cnt": 5}]
