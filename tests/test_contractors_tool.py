"""Tests for the contractors NL tool."""

from unittest.mock import MagicMock, patch

from backend.brain.tools.contractors import make_contractors_tool


def _call(action, **kwargs):
    tool = make_contractors_tool()
    args = {"action": action, **kwargs}
    ctx = MagicMock()
    return tool.fn(args, ctx)


# ── Lookup ──────────────────────────────────────────────────────────


@patch("backend.brain.tools.contractors.load_all_contractors", return_value=[])
@patch("backend.brain.tools.contractors.fuzzy_find")
def test_lookup_found(mock_fuzzy, *_):
    c = MagicMock()
    c.id = "c1"
    c.display_name = "Test Author"
    c.is_stub = False
    c.type = MagicMock(value="самозанятый")
    mock_fuzzy.return_value = [(c, 0.85)]

    result = _call("lookup", name="Test")

    assert "contractors" in result
    assert result["contractors"][0]["name"] == "Test Author"
    assert result["contractors"][0]["score"] == 0.85


@patch("backend.brain.tools.contractors.load_all_contractors", return_value=[])
@patch("backend.brain.tools.contractors.fuzzy_find", return_value=[])
def test_lookup_not_found(*_):
    result = _call("lookup", name="Nobody")

    assert result["suggestions"] == []


# ── Create stub ─────────────────────────────────────────────────────


@patch("backend.brain.tools.contractors.load_all_contractors", return_value=[])
@patch("backend.brain.tools.contractors.fuzzy_find", return_value=[])
@patch("backend.brain.tools.contractors.ContractorFactory")
def test_create_stub_success(mock_factory_cls, *_):
    stub = MagicMock()
    stub.id = "s1"
    stub.display_name = "New Author"
    mock_factory_cls.return_value.create_stub.return_value = (stub, "SECRET")

    result = _call("create_stub", name="New Author")

    assert "created" in result
    assert result["created"]["id"] == "s1"
    assert result["created"]["secret_code"] == "SECRET"


@patch("backend.brain.tools.contractors.load_all_contractors", return_value=[])
@patch("backend.brain.tools.contractors.fuzzy_find")
def test_create_stub_duplicate(mock_fuzzy, *_):
    c = MagicMock()
    c.display_name = "Existing Author"
    mock_fuzzy.return_value = [(c, 0.95)]

    result = _call("create_stub", name="Existing Author")

    assert "error" in result


# ── Add redirect ────────────────────────────────────────────────────


@patch("backend.brain.tools.contractors.add_redirect_rule")
@patch("backend.brain.tools.contractors.load_all_contractors", return_value=[])
@patch("backend.brain.tools.contractors.find_contractor")
def test_add_redirect(mock_find, _, mock_add):
    target = MagicMock()
    target.id = "c1"
    target.display_name = "Editor"
    mock_find.return_value = target

    result = _call("add_redirect", source_name="Alias", target_name="Editor")

    assert "confirmation" in result
    mock_add.assert_called_once_with("Alias", "c1")


# ── Set rate ────────────────────────────────────────────────────────


@patch("backend.brain.tools.contractors.upsert_article_rate_rule")
@patch("backend.brain.tools.contractors.load_all_contractors", return_value=[])
@patch("backend.brain.tools.contractors.find_contractor")
def test_set_rate(mock_find, _, mock_upsert):
    c = MagicMock()
    c.id = "c1"
    c.display_name = "Author"
    mock_find.return_value = c

    result = _call("set_rate", name="Author", eur=150, rub=0)

    assert "confirmation" in result
    mock_upsert.assert_called_once_with("c1", eur=150, rub=0)


# ── Get rate ────────────────────────────────────────────────────────


@patch("backend.brain.tools.contractors.load_all_contractors", return_value=[])
@patch("backend.brain.tools.contractors.find_contractor")
@patch("backend.brain.tools.contractors.get_article_rate_rule")
def test_get_rate_exists(mock_get_rate, mock_find, *_):
    c = MagicMock()
    c.id = "c1"
    c.display_name = "Author"
    mock_find.return_value = c
    rule = MagicMock()
    rule.eur = 150
    rule.rub = 0
    mock_get_rate.return_value = rule

    result = _call("get_rate", name="Author")

    assert result["eur"] == 150
    assert result["rub"] == 0


@patch("backend.brain.tools.contractors.load_all_contractors", return_value=[])
@patch("backend.brain.tools.contractors.find_contractor")
@patch("backend.brain.tools.contractors.get_article_rate_rule", return_value=None)
def test_get_rate_missing(mock_get_rate, mock_find, *_):
    c = MagicMock()
    c.id = "c1"
    c.display_name = "Author"
    mock_find.return_value = c

    result = _call("get_rate", name="Author")

    assert "result" in result
    assert "не задана" in result["result"]
