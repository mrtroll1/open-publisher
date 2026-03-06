from unittest.mock import MagicMock

from backend.commands.contractor.sync_entities import _build_summary, execute
from common.models import ContractorType, RoleCode


def _mock_contractor(
    name="Иванов Иван",
    ctype=ContractorType.SAMOZANYATY,
    role_code=RoleCode.AUTHOR,
    mags="Republic",
    telegram="12345",
    email="ivan@test.com",
):
    c = MagicMock()
    c.display_name = name
    c.type = ctype
    c.role_code = role_code
    c.mags = mags
    c.telegram = telegram
    c.email = email
    return c


# ===================================================================
#  _build_summary
# ===================================================================

class TestBuildSummary:

    def test_full_summary(self):
        c = _mock_contractor()
        s = _build_summary(c)
        assert "Иванов Иван" in s
        assert "самозанятый" in s
        assert "автор" in s
        assert "Republic" in s
        assert "telegram: да" in s

    def test_no_telegram(self):
        c = _mock_contractor(telegram="")
        s = _build_summary(c)
        assert "telegram: нет" in s

    def test_no_mags(self):
        c = _mock_contractor(mags="")
        s = _build_summary(c)
        assert "издания" not in s

    def test_ip_editor(self):
        c = _mock_contractor(ctype=ContractorType.IP, role_code=RoleCode.REDAKTOR)
        s = _build_summary(c)
        assert "ИП" in s
        assert "редактор" in s

    def test_global_korrektor(self):
        c = _mock_contractor(ctype=ContractorType.GLOBAL, role_code=RoleCode.KORREKTOR)
        s = _build_summary(c)
        assert "global" in s
        assert "корректор" in s


# ===================================================================
#  execute — create new entities
# ===================================================================

class TestExecuteCreate:

    def test_creates_new_entity(self):
        db = MagicMock()
        db.find_entity_by_external_id.return_value = None
        embed = MagicMock()
        embed.embed_one.return_value = [0.1, 0.2]

        c = _mock_contractor()
        created, updated = execute([c], db, embed)

        assert created == 1
        assert updated == 0
        db.save_entity.assert_called_once()
        call_kwargs = db.save_entity.call_args[1]
        assert call_kwargs["kind"] == "person"
        assert call_kwargs["name"] == "Иванов Иван"
        assert call_kwargs["external_ids"]["contractor_name"] == "Иванов Иван"
        assert call_kwargs["external_ids"]["contractor_type"] == "самозанятый"
        assert call_kwargs["embedding"] == [0.1, 0.2]
        embed.embed_one.assert_called_once_with("Иванов Иван самозанятый")

    def test_creates_multiple(self):
        db = MagicMock()
        db.find_entity_by_external_id.return_value = None
        embed = MagicMock()
        embed.embed_one.return_value = [0.0]

        contractors = [_mock_contractor(name="A"), _mock_contractor(name="B")]
        created, updated = execute(contractors, db, embed)

        assert created == 2
        assert updated == 0
        assert db.save_entity.call_count == 2


# ===================================================================
#  execute — update existing entities
# ===================================================================

class TestExecuteUpdate:

    def test_updates_existing_entity(self):
        db = MagicMock()
        db.find_entity_by_external_id.return_value = {"id": "entity-1"}
        embed = MagicMock()

        c = _mock_contractor()
        created, updated = execute([c], db, embed)

        assert created == 0
        assert updated == 1
        db.update_entity.assert_called_once()
        call_args = db.update_entity.call_args[0]
        assert call_args[0] == "entity-1"
        embed.embed_one.assert_not_called()

    def test_mixed_create_and_update(self):
        db = MagicMock()
        db.find_entity_by_external_id.side_effect = [
            None,
            {"id": "entity-2"},
            None,
        ]
        embed = MagicMock()
        embed.embed_one.return_value = [0.0]

        contractors = [
            _mock_contractor(name="New1"),
            _mock_contractor(name="Existing"),
            _mock_contractor(name="New2"),
        ]
        created, updated = execute(contractors, db, embed)

        assert created == 2
        assert updated == 1


# ===================================================================
#  execute — telegram_id in external_ids
# ===================================================================

class TestTelegramId:

    def test_telegram_id_included_when_present(self):
        db = MagicMock()
        db.find_entity_by_external_id.return_value = None
        embed = MagicMock()
        embed.embed_one.return_value = [0.0]

        c = _mock_contractor(telegram="99999")
        execute([c], db, embed)

        call_kwargs = db.save_entity.call_args[1]
        assert call_kwargs["external_ids"]["telegram_id"] == "99999"

    def test_telegram_id_excluded_when_empty(self):
        db = MagicMock()
        db.find_entity_by_external_id.return_value = None
        embed = MagicMock()
        embed.embed_one.return_value = [0.0]

        c = _mock_contractor(telegram="")
        execute([c], db, embed)

        call_kwargs = db.save_entity.call_args[1]
        assert "telegram_id" not in call_kwargs["external_ids"]

    def test_empty_list_returns_zero(self):
        db = MagicMock()
        embed = MagicMock()

        created, updated = execute([], db, embed)

        assert created == 0
        assert updated == 0
        db.save_entity.assert_not_called()
        db.update_entity.assert_not_called()
