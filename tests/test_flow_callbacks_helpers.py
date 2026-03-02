"""Tests for pure helper functions in telegram_bot/flow_callbacks.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.models import (
    ArticleEntry,
    ContractorType,
    GlobalContractor,
    IPContractor,
    RoleCode,
    SamozanyatyContractor,
)
from telegram_bot.flow_callbacks import (
    _dup_button_label,
    _extract_bot_mention,
    _GROUP_COMMAND_HANDLERS,
    _COMMAND_DESCRIPTIONS,
    _ROLE_LABELS,
    handle_code_rate_callback,
)
from telegram_bot import replies


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _global(**overrides) -> GlobalContractor:
    kwargs = dict(
        id="g1", name_en="Test Global", address="Addr", email="a@b.c",
        bank_name="Bank", bank_account="ACC", swift="SWIFT",
    )
    kwargs.update(overrides)
    return GlobalContractor(**kwargs)


def _samoz(**overrides) -> SamozanyatyContractor:
    kwargs = dict(
        id="s1", name_ru="Тест Самозанятый", address="Адрес", email="s@t.ru",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890", inn="123456789012",
    )
    kwargs.update(overrides)
    return SamozanyatyContractor(**kwargs)


def _ip(**overrides) -> IPContractor:
    kwargs = dict(
        id="ip1", name_ru="Тест ИП", email="ip@test.ru",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890",
        passport_issued_by="УФМС", passport_issued_date="01.01.2020",
        passport_code="123-456", ogrnip="123456789012345",
    )
    kwargs.update(overrides)
    return IPContractor(**kwargs)


# ===================================================================
#  _dup_button_label()
# ===================================================================

class TestDupButtonLabel:

    def test_no_aliases_returns_display_name(self):
        c = _global(aliases=[])
        assert _dup_button_label(c) == "Test Global"

    def test_alias_same_as_display_name(self):
        c = _global(name_en="Test Global", aliases=["Test Global"])
        assert _dup_button_label(c) == "Test Global"

    def test_alias_different_from_display_name(self):
        c = _global(name_en="Real Name", aliases=["Alias Name"])
        result = _dup_button_label(c)
        assert result == "Alias Name (Real Name)"

    def test_samozanyaty_with_alias(self):
        c = _samoz(name_ru="Иван Иванов", aliases=["Псевдоним"])
        result = _dup_button_label(c)
        assert result == "Псевдоним (Иван Иванов)"

    def test_samozanyaty_no_alias(self):
        c = _samoz(name_ru="Иван Иванов", aliases=[])
        result = _dup_button_label(c)
        assert result == "Иван Иванов"

    def test_ip_with_alias(self):
        c = _ip(name_ru="Пётр Петров", aliases=["Автор"])
        result = _dup_button_label(c)
        assert result == "Автор (Пётр Петров)"

    def test_multiple_aliases_uses_first(self):
        c = _global(name_en="Real", aliases=["First", "Second", "Third"])
        result = _dup_button_label(c)
        assert result == "First (Real)"


# ===================================================================
#  _extract_bot_mention()
# ===================================================================

class TestExtractBotMention:

    def test_mention_with_space(self):
        result = _extract_bot_mention("@republic_bot проверь сайт", "republic_bot")
        assert result == "проверь сайт"

    def test_mention_with_newline(self):
        result = _extract_bot_mention("@republic_bot\nпроверь сайт", "republic_bot")
        assert result == "проверь сайт"

    def test_no_mention_returns_none(self):
        result = _extract_bot_mention("просто текст", "republic_bot")
        assert result is None

    def test_mention_without_separator_returns_none(self):
        result = _extract_bot_mention("@republic_bot", "republic_bot")
        assert result is None

    def test_mention_wrong_username_returns_none(self):
        result = _extract_bot_mention("@other_bot проверь сайт", "republic_bot")
        assert result is None

    def test_mention_in_middle_returns_none(self):
        result = _extract_bot_mention("привет @republic_bot проверь", "republic_bot")
        assert result is None

    def test_strips_whitespace(self):
        result = _extract_bot_mention("@republic_bot   пробелы   ", "republic_bot")
        assert result == "пробелы"

    def test_multiline_message(self):
        result = _extract_bot_mention("@republic_bot первая строка\nвторая строка", "republic_bot")
        assert result == "первая строка\nвторая строка"


# ===================================================================
#  _GROUP_COMMAND_HANDLERS
# ===================================================================

class TestGroupCommandHandlers:

    def test_health_registered(self):
        assert "health" in _GROUP_COMMAND_HANDLERS

    def test_tech_support_registered(self):
        assert "tech_support" in _GROUP_COMMAND_HANDLERS

    def test_code_registered(self):
        assert "code" in _GROUP_COMMAND_HANDLERS

    def test_handlers_are_callable(self):
        for name, handler in _GROUP_COMMAND_HANDLERS.items():
            assert callable(handler), f"Handler for {name} is not callable"

    def test_expected_commands_only(self):
        assert set(_GROUP_COMMAND_HANDLERS.keys()) == {"health", "tech_support", "code", "articles", "lookup"}


# ===================================================================
#  _COMMAND_DESCRIPTIONS
# ===================================================================

class TestCommandDescriptions:

    def test_all_handlers_have_descriptions(self):
        for cmd in _GROUP_COMMAND_HANDLERS:
            assert cmd in _COMMAND_DESCRIPTIONS, f"Missing description for {cmd}"

    def test_descriptions_are_strings(self):
        for cmd, desc in _COMMAND_DESCRIPTIONS.items():
            assert isinstance(desc, str), f"Description for {cmd} is not a string"

    def test_descriptions_not_empty(self):
        for cmd, desc in _COMMAND_DESCRIPTIONS.items():
            assert desc.strip(), f"Description for {cmd} is empty"

    def test_expected_descriptions(self):
        assert set(_COMMAND_DESCRIPTIONS.keys()) == {"health", "tech_support", "code", "articles", "lookup"}


# ===================================================================
#  _ROLE_LABELS / _TYPE_LABELS
# ===================================================================

class TestRoleLabels:

    def test_author(self):
        assert _ROLE_LABELS[RoleCode.AUTHOR] == "автор"

    def test_redaktor(self):
        assert _ROLE_LABELS[RoleCode.REDAKTOR] == "редактор"

    def test_korrektor(self):
        assert _ROLE_LABELS[RoleCode.KORREKTOR] == "корректор"

    def test_covers_all_roles(self):
        assert set(_ROLE_LABELS.keys()) == set(RoleCode)


class TestTypeLabels:

    def test_samozanyaty(self):
        assert ContractorType.SAMOZANYATY.value == "самозанятый"

    def test_ip(self):
        assert ContractorType.IP.value == "ИП"

    def test_global(self):
        assert ContractorType.GLOBAL.value == "global"


# ===================================================================
#  /articles output formatting
# ===================================================================

class TestArticlesFormatting:

    def test_article_ids_list_format(self):
        articles = [
            ArticleEntry(article_id="12345"),
            ArticleEntry(article_id="67890"),
            ArticleEntry(article_id="11111"),
        ]
        ids_list = "\n".join(f"  - {a.article_id}" for a in articles)
        assert ids_list == "  - 12345\n  - 67890\n  - 11111"

    def test_full_output_format(self):
        contractor = _samoz(name_ru="Иван Иванов", role_code=RoleCode.AUTHOR)
        articles = [ArticleEntry(article_id="100"), ArticleEntry(article_id="200")]
        month = "2026-02"

        role_label = _ROLE_LABELS.get(contractor.role_code, contractor.role_code.value)
        ids_list = "\n".join(f"  - {a.article_id}" for a in articles)
        text = (
            f"{contractor.display_name} ({role_label})\n"
            f"Месяц: {month}\n"
            f"Статей: {len(articles)}\n\n"
            f"{ids_list}"
        )

        assert text == (
            "Иван Иванов (автор)\n"
            "Месяц: 2026-02\n"
            "Статей: 2\n\n"
            "  - 100\n"
            "  - 200"
        )

    def test_redaktor_role_label_in_output(self):
        contractor = _global(name_en="Jane Doe", role_code=RoleCode.REDAKTOR)
        role_label = _ROLE_LABELS.get(contractor.role_code, contractor.role_code.value)
        header = f"{contractor.display_name} ({role_label})"
        assert header == "Jane Doe (редактор)"


# ===================================================================
#  /lookup — no sensitive data exposure
# ===================================================================

class TestLookupNoSensitiveData:

    def _build_lookup_output(self, contractor) -> str:
        type_label = contractor.type.value
        role_label = _ROLE_LABELS.get(contractor.role_code, contractor.role_code.value)
        tg_status = "привязан" if contractor.telegram else "не привязан"
        has_bank = bool(contractor.bank_name and contractor.bank_account)
        bank_status = "заполнены" if has_bank else "не заполнены"

        lines = [
            f"{contractor.display_name}",
            f"Тип: {type_label}",
            f"Роль: {role_label}",
        ]
        if contractor.mags:
            lines.append(f"Издания: {contractor.mags}")
        if contractor.email:
            lines.append(f"Email: {contractor.email}")
        lines.append(f"Telegram: {tg_status}")
        lines.append(f"Номер счёта: {contractor.invoice_number}")
        lines.append(f"Банковские данные: {bank_status}")
        return "\n".join(lines)

    def test_samozanyaty_hides_sensitive_fields(self):
        c = _samoz(
            passport_series="9876", passport_number="543210",
            inn="111222333444", bank_account="40817810000000000001",
            bik="044525225", corr_account="30101810400000000225",
            secret_code="SECRET123",
        )
        output = self._build_lookup_output(c)
        assert "9876" not in output
        assert "543210" not in output
        assert "111222333444" not in output
        assert "40817810000000000001" not in output
        assert "044525225" not in output
        assert "30101810400000000225" not in output
        assert "SECRET123" not in output

    def test_ip_hides_sensitive_fields(self):
        c = _ip(
            passport_series="1111", passport_number="222222",
            passport_issued_by="УФМС по г. Москве",
            passport_issued_date="15.06.2018",
            passport_code="770-001",
            ogrnip="999888777666555",
            bank_account="40802810000000000002",
            bik="044525226", corr_account="30101810400000000226",
            secret_code="TOPSECRET",
        )
        output = self._build_lookup_output(c)
        assert "1111" not in output
        assert "222222" not in output
        assert "УФМС по г. Москве" not in output
        assert "15.06.2018" not in output
        assert "770-001" not in output
        assert "999888777666555" not in output
        assert "40802810000000000002" not in output
        assert "044525226" not in output
        assert "30101810400000000226" not in output
        assert "TOPSECRET" not in output

    def test_global_hides_sensitive_fields(self):
        c = _global(
            address="123 Secret Street, London",
            bank_account="GB29NWBK60161331926819",
            swift="NWBKGB2L",
            secret_code="GLOBALSECRET",
        )
        output = self._build_lookup_output(c)
        assert "123 Secret Street" not in output
        assert "GB29NWBK60161331926819" not in output
        assert "NWBKGB2L" not in output
        assert "GLOBALSECRET" not in output

    def test_lookup_shows_expected_fields(self):
        c = _samoz(
            name_ru="Иван Петров", email="ivan@test.ru",
            mags="republic", telegram="@ivan",
            role_code=RoleCode.AUTHOR, invoice_number=42,
        )
        output = self._build_lookup_output(c)
        assert "Иван Петров" in output
        assert "самозанятый" in output
        assert "автор" in output
        assert "republic" in output
        assert "ivan@test.ru" in output
        assert "привязан" in output
        assert "42" in output
        assert "заполнены" in output

    def test_telegram_not_linked(self):
        c = _global(telegram="")
        output = self._build_lookup_output(c)
        assert "не привязан" in output

    def test_bank_data_not_filled(self):
        c = _global(bank_name="", bank_account="")
        output = self._build_lookup_output(c)
        assert "не заполнены" in output


# ===================================================================
#  Fuzzy suggestion formatting
# ===================================================================

class TestFuzzySuggestionFormatting:

    def test_suggestion_line_format(self):
        c = _samoz(name_ru="Анна Сидорова")
        line = f"  - {c.display_name} ({c.type.value})"
        assert line == "  - Анна Сидорова (самозанятый)"

    def test_suggestion_line_ip(self):
        c = _ip(name_ru="Пётр Петров")
        line = f"  - {c.display_name} ({c.type.value})"
        assert line == "  - Пётр Петров (ИП)"

    def test_suggestion_line_global(self):
        c = _global(name_en="John Smith")
        line = f"  - {c.display_name} ({c.type.value})"
        assert line == "  - John Smith (global)"

    def test_full_suggestions_message(self):
        contractors = [
            _samoz(name_ru="Анна Сидорова"),
            _ip(name_ru="Пётр Петров"),
            _global(name_en="John Smith"),
        ]
        suggestions = "\n".join(
            f"  - {c.display_name} ({c.type.value})" for c in contractors
        )
        msg = replies.lookup.fuzzy_suggestions.format(suggestions=suggestions)
        assert msg == (
            "Точного совпадения нет. Возможные варианты:\n"
            "  - Анна Сидорова (самозанятый)\n"
            "  - Пётр Петров (ИП)\n"
            "  - John Smith (global)"
        )


# ===================================================================
#  handle_code_rate_callback
# ===================================================================

def _make_callback(data: str) -> MagicMock:
    cb = AsyncMock()
    cb.data = data
    cb.message = AsyncMock()
    return cb


class TestHandleCodeRateCallback:

    @patch("telegram_bot.flow_callbacks._db")
    def test_valid_rating(self, mock_db):
        cb = _make_callback("code_rate:task-abc-123:4")
        asyncio.run(handle_code_rate_callback(cb))

        mock_db.rate_code_task.assert_called_once_with("task-abc-123", 4)
        cb.answer.assert_awaited_once_with("Оценка сохранена!")
        cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)

    def test_invalid_format_too_few_parts(self):
        cb = _make_callback("code_rate:missing")
        asyncio.run(handle_code_rate_callback(cb))

        cb.answer.assert_awaited_once_with()

    def test_invalid_format_too_many_parts(self):
        cb = _make_callback("code_rate:id:3:extra")
        asyncio.run(handle_code_rate_callback(cb))

        cb.answer.assert_awaited_once_with()

    @patch("telegram_bot.flow_callbacks._db")
    def test_db_error_still_answers(self, mock_db):
        mock_db.rate_code_task.side_effect = RuntimeError("db down")

        cb = _make_callback("code_rate:task-xyz:5")
        asyncio.run(handle_code_rate_callback(cb))

        cb.answer.assert_awaited_once_with("Оценка сохранена!")
        cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
