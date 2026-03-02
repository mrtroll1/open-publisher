"""Tests for backend/infrastructure/gateways/republic_gateway.py"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from common.models import GlobalContractor, RoleCode


# ===================================================================
#  _api_get() — retry logic, response parsing
# ===================================================================

class TestApiGet:

    def _gw(self):
        from backend.infrastructure.gateways.republic_gateway import RepublicGateway
        return RepublicGateway()

    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_returns_data_from_dollar_data_key(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            content=b"ok",
            json=lambda: {"$data": [1, 2, 3]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        gw = self._gw()
        result = gw._api_get("http://api/posts", {}, "test")
        assert result == [1, 2, 3]

    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_returns_data_from_data_key(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            content=b"ok",
            json=lambda: {"data": [4, 5]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        gw = self._gw()
        result = gw._api_get("http://api/posts", {}, "test")
        assert result == [4, 5]

    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_dollar_data_takes_precedence(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            content=b"ok",
            json=lambda: {"$data": [1], "data": [2]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        gw = self._gw()
        result = gw._api_get("http://api/posts", {}, "test")
        assert result == [1]

    @patch("backend.infrastructure.gateways.republic_gateway.time.sleep")
    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_retries_on_5xx(self, mock_get, mock_sleep):
        resp_500 = MagicMock(status_code=500, content=b"err", text="Internal Server Error")
        resp_200 = MagicMock(
            status_code=200, content=b"ok",
            json=lambda: {"$data": [10]},
        )
        resp_200.raise_for_status = MagicMock()
        mock_get.side_effect = [resp_500, resp_200]

        gw = self._gw()
        result = gw._api_get("http://api/posts", {}, "test")
        assert result == [10]
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("backend.infrastructure.gateways.republic_gateway.time.sleep")
    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_returns_empty_after_max_retries_5xx(self, mock_get, mock_sleep):
        resp_500 = MagicMock(status_code=503, content=b"err", text="Service Unavailable")
        mock_get.return_value = resp_500

        gw = self._gw()
        result = gw._api_get("http://api/posts", {}, "test")
        assert result == []
        assert mock_get.call_count == 3  # MAX_RETRIES = 3

    @patch("backend.infrastructure.gateways.republic_gateway.time.sleep")
    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_retries_on_timeout(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            requests.Timeout("timed out"),
            MagicMock(
                status_code=200, content=b"ok",
                json=lambda: {"$data": [7]},
                raise_for_status=MagicMock(),
            ),
        ]
        gw = self._gw()
        result = gw._api_get("http://api/posts", {}, "test")
        assert result == [7]

    @patch("backend.infrastructure.gateways.republic_gateway.time.sleep")
    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_retries_on_connection_error(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            requests.ConnectionError("refused"),
            MagicMock(
                status_code=200, content=b"ok",
                json=lambda: {"$data": [8]},
                raise_for_status=MagicMock(),
            ),
        ]
        gw = self._gw()
        result = gw._api_get("http://api/posts", {}, "test")
        assert result == [8]

    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_4xx_returns_empty(self, mock_get):
        resp = MagicMock(status_code=404, content=b"nf", text="Not Found")
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        mock_get.return_value = resp
        gw = self._gw()
        result = gw._api_get("http://api/posts", {}, "test")
        assert result == []

    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_empty_data_returns_empty_list(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, content=b"ok",
            json=lambda: {"$data": []},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        gw = self._gw()
        result = gw._api_get("http://api/posts", {}, "test")
        assert result == []


# ===================================================================
#  fetch_articles() — routing and dedup
# ===================================================================

class TestFetchArticles:

    def _gw(self):
        from backend.infrastructure.gateways.republic_gateway import RepublicGateway
        return RepublicGateway()

    def _make_contractor(self, mags="", aliases=None, display_name="Test Author"):
        return GlobalContractor(
            id="test",
            name_en=display_name,
            aliases=aliases or [],
            role_code=RoleCode.AUTHOR,
            email="t@t.com",
            bank_name="B",
            bank_account="A",
            swift="S",
            address="Addr",
            mags=mags,
        )

    @patch("backend.infrastructure.gateways.republic_gateway.RepublicGateway._api_get")
    def test_mag_based_route(self, mock_api):
        mock_api.return_value = [100, 200]
        gw = self._gw()
        c = self._make_contractor(mags="mag1, mag2")
        articles = gw.fetch_articles(c, "2026-01")
        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert "by-magazine" in call_args[0][0]
        assert len(articles) == 2
        assert articles[0].article_id == "100"

    @patch("backend.infrastructure.gateways.republic_gateway.RepublicGateway._api_get")
    def test_author_based_route(self, mock_api):
        mock_api.return_value = [300]
        gw = self._gw()
        c = self._make_contractor(aliases=["Alias One"])
        articles = gw.fetch_articles(c, "2026-01")
        # Called once for each name (Alias One + display_name)
        assert mock_api.call_count == 2

    @patch("backend.infrastructure.gateways.republic_gateway.RepublicGateway._api_get")
    def test_author_deduplication(self, mock_api):
        mock_api.side_effect = [[1, 2, 3], [2, 3, 4]]
        gw = self._gw()
        c = self._make_contractor(aliases=["Alt Name"])
        articles = gw.fetch_articles(c, "2026-01")
        ids = [a.article_id for a in articles]
        assert ids == ["1", "2", "3", "4"]

    @patch("backend.infrastructure.gateways.republic_gateway.RepublicGateway._api_get")
    def test_no_aliases_no_display_name_returns_empty(self, mock_api):
        """When contractor has no aliases, no mags, and display_name is empty,
        fetch_articles returns [] without calling the API."""
        gw = self._gw()
        # Use a MagicMock to simulate a contractor with truly empty names
        c = MagicMock()
        c.mags = ""
        c.aliases = []
        c.display_name = ""
        c.id = "test"
        articles = gw.fetch_articles(c, "2026-01")
        assert articles == []
        mock_api.assert_not_called()


# ===================================================================
#  fetch_published_authors()
# ===================================================================

class TestFetchPublishedAuthors:

    def _gw(self):
        from backend.infrastructure.gateways.republic_gateway import RepublicGateway
        return RepublicGateway()

    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_parses_authors(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"$data": [
                {"author": "Alice", "post_count": 5},
                {"author": "Bob", "post_count": 2},
            ]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        gw = self._gw()
        result = gw.fetch_published_authors("2026-01")
        assert len(result) == 2
        assert result[0] == {"author": "Alice", "post_count": 5}

    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_skips_malformed_rows(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"$data": [
                {"author": "Alice", "post_count": 3},
                "not_a_dict",
                {"no_author_key": True, "post_count": 1},
            ]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        gw = self._gw()
        result = gw.fetch_published_authors("2026-01")
        assert len(result) == 1

    @patch("backend.infrastructure.gateways.republic_gateway.requests.get")
    def test_api_error_returns_empty(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("fail")
        gw = self._gw()
        result = gw.fetch_published_authors("2026-01")
        assert result == []
