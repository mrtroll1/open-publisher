from unittest.mock import MagicMock, patch

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo, _SCHEMA_SQL


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _make_repo_with_conn(closed=False):
    repo = BasePostgresRepo()
    mock_cursor = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_cursor)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.closed = closed
    mock_conn.cursor.return_value = mock_ctx
    repo._conn = mock_conn
    return repo, mock_conn, mock_cursor


# ===================================================================
#  __init__
# ===================================================================

class TestInit:

    def test_conn_starts_as_none(self):
        repo = BasePostgresRepo()
        assert repo._conn is None


# ===================================================================
#  _get_conn
# ===================================================================

class TestGetConn:

    @patch("backend.infrastructure.repositories.postgres.base.psycopg2")
    @patch("backend.infrastructure.repositories.postgres.base.DATABASE_URL", "postgres://test")
    def test_creates_connection_on_first_call(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn

        repo = BasePostgresRepo()
        result = repo._get_conn()

        mock_psycopg2.connect.assert_called_once_with("postgres://test")
        assert result is mock_conn
        assert mock_conn.autocommit is True

    @patch("backend.infrastructure.repositories.postgres.base.psycopg2")
    @patch("backend.infrastructure.repositories.postgres.base.DATABASE_URL", "postgres://test")
    def test_reuses_open_connection(self, mock_psycopg2):
        repo, mock_conn, _ = _make_repo_with_conn(closed=False)

        result = repo._get_conn()

        mock_psycopg2.connect.assert_not_called()
        assert result is mock_conn

    @patch("backend.infrastructure.repositories.postgres.base.psycopg2")
    @patch("backend.infrastructure.repositories.postgres.base.DATABASE_URL", "postgres://test")
    def test_reconnects_if_closed(self, mock_psycopg2):
        new_conn = MagicMock()
        mock_psycopg2.connect.return_value = new_conn

        repo = BasePostgresRepo()
        old_conn = MagicMock()
        old_conn.closed = True
        repo._conn = old_conn

        result = repo._get_conn()

        mock_psycopg2.connect.assert_called_once_with("postgres://test")
        assert result is new_conn
        assert new_conn.autocommit is True

    @patch("backend.infrastructure.repositories.postgres.base.psycopg2")
    @patch("backend.infrastructure.repositories.postgres.base.DATABASE_URL", "postgres://test")
    def test_second_call_reuses(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_psycopg2.connect.return_value = mock_conn

        repo = BasePostgresRepo()
        first = repo._get_conn()
        second = repo._get_conn()

        assert first is second
        assert mock_psycopg2.connect.call_count == 1


# ===================================================================
#  init_schema
# ===================================================================

class TestInitSchema:

    def test_executes_schema_sql_and_seeds(self):
        repo, mock_conn, mock_cursor = _make_repo_with_conn()

        with patch.object(repo, "_seed_bindings") as mock_seed:
            repo.init_schema()

        mock_cursor.execute.assert_called_once_with(_SCHEMA_SQL)
        mock_seed.assert_called_once()


# ===================================================================
#  _seed_bindings
# ===================================================================

class TestSeedBindings:

    @patch("common.config.ADMIN_TELEGRAM_IDS", [111, 222])
    @patch("common.config.EDITORIAL_CHAT_ID", 500)
    def test_seeds_editorial_and_admin_bindings(self):
        repo, mock_conn, mock_cursor = _make_repo_with_conn()

        repo._seed_bindings()

        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 3

        # First call: editorial binding
        sql0, params0 = calls[0][0]
        assert "INSERT INTO environment_bindings" in sql0
        assert params0 == (500, "editorial_group")

        # Second/third calls: admin bindings
        sql1, params1 = calls[1][0]
        assert params1 == (111, "admin_dm")

        sql2, params2 = calls[2][0]
        assert params2 == (222, "admin_dm")

    @patch("common.config.ADMIN_TELEGRAM_IDS", [111])
    @patch("common.config.EDITORIAL_CHAT_ID", 0)
    def test_skips_editorial_when_chat_id_zero(self):
        repo, mock_conn, mock_cursor = _make_repo_with_conn()

        repo._seed_bindings()

        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 1
        _, params = calls[0][0]
        assert params == (111, "admin_dm")

    @patch("common.config.ADMIN_TELEGRAM_IDS", [])
    @patch("common.config.EDITORIAL_CHAT_ID", 500)
    def test_seeds_editorial_only_when_no_admins(self):
        repo, mock_conn, mock_cursor = _make_repo_with_conn()

        repo._seed_bindings()

        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 1
        _, params = calls[0][0]
        assert params == (500, "editorial_group")

    @patch("common.config.ADMIN_TELEGRAM_IDS", [])
    @patch("common.config.EDITORIAL_CHAT_ID", 0)
    def test_no_bindings_when_all_zero(self):
        repo, mock_conn, mock_cursor = _make_repo_with_conn()

        repo._seed_bindings()

        mock_cursor.execute.assert_not_called()

    @patch("common.config.ADMIN_TELEGRAM_IDS", [111])
    @patch("common.config.EDITORIAL_CHAT_ID", 500)
    def test_uses_on_conflict_do_nothing(self):
        repo, mock_conn, mock_cursor = _make_repo_with_conn()

        repo._seed_bindings()

        for c in mock_cursor.execute.call_args_list:
            sql = c[0][0]
            assert "ON CONFLICT DO NOTHING" in sql


# ===================================================================
#  close
# ===================================================================

class TestClose:

    def test_closes_open_connection(self):
        repo, mock_conn, _ = _make_repo_with_conn(closed=False)

        repo.close()

        mock_conn.close.assert_called_once()
        assert repo._conn is None

    def test_noop_on_none_connection(self):
        repo = BasePostgresRepo()

        repo.close()  # Should not raise

        assert repo._conn is None

    def test_noop_on_already_closed(self):
        repo = BasePostgresRepo()
        mock_conn = MagicMock()
        mock_conn.closed = True
        repo._conn = mock_conn

        repo.close()

        mock_conn.close.assert_not_called()
