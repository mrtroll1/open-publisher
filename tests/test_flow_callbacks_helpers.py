"""Tests for pure helper functions in telegram_bot/flow_callbacks.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.models import (
    ArticleEntry,
    ContractorType,
    GlobalContractor,
    IncomingEmail,
    IPContractor,
    RoleCode,
    SamozanyatyContractor,
    SupportDraft,
)
from telegram_bot.flow_callbacks import (
    _admin_reply_map,
    _dup_button_label,
    _extract_bot_mention,
    _format_reply_chain,
    _GREETING_PREFIXES,
    _GROUP_COMMAND_HANDLERS,
    _COMMAND_DESCRIPTIONS,
    _handle_draft_reply,
    _handle_nl_reply,
    _ROLE_LABELS,
    _save_turn,
    _send_html,
    _support_draft_map,
    handle_admin_reply,
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

    def test_support_registered(self):
        assert "support" in _GROUP_COMMAND_HANDLERS

    def test_handlers_are_callable(self):
        for name, handler in _GROUP_COMMAND_HANDLERS.items():
            assert callable(handler), f"Handler for {name} is not callable"

    def test_expected_commands_only(self):
        assert set(_GROUP_COMMAND_HANDLERS.keys()) == {"health", "support", "articles", "lookup"}


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
        assert set(_COMMAND_DESCRIPTIONS.keys()) == {"health", "support", "articles", "lookup"}


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


# ===================================================================
#  _save_turn()
# ===================================================================

def _make_message(chat_id=100, chat_type="private", user_id=42, message_id=10):
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.chat.type = chat_type
    msg.from_user.id = user_id
    msg.message_id = message_id
    return msg


def _make_sent(message_id=11):
    sent = MagicMock()
    sent.message_id = message_id
    return sent


class TestSaveTurn:

    @patch("telegram_bot.flow_callbacks._db")
    def test_save_turn_saves_both_turns(self, mock_db):
        mock_db.save_conversation.return_value = "user-uuid"
        msg = _make_message()
        sent = _make_sent()

        asyncio.run(_save_turn(msg, sent, "hello", "hi back", {"command": "code"}))

        assert mock_db.save_conversation.call_count == 2

    @patch("telegram_bot.flow_callbacks._db")
    def test_save_turn_links_reply_to_id(self, mock_db):
        mock_db.save_conversation.return_value = "user-turn-uuid"
        msg = _make_message()
        sent = _make_sent()

        asyncio.run(_save_turn(msg, sent, "hello", "hi back", {}))

        calls = mock_db.save_conversation.call_args_list
        # First call (user turn) has no reply_to_id
        user_call_kwargs = calls[0][1]
        assert user_call_kwargs.get("reply_to_id") is None
        # Second call (assistant turn) links to user turn UUID
        assistant_call_kwargs = calls[1][1]
        assert assistant_call_kwargs["reply_to_id"] == "user-turn-uuid"

    @patch("telegram_bot.flow_callbacks._db")
    def test_save_turn_with_parent_id_links_user_entry(self, mock_db):
        mock_db.save_conversation.return_value = "user-turn-uuid"
        msg = _make_message()
        sent = _make_sent()

        asyncio.run(_save_turn(msg, sent, "hello", "hi back", {}, parent_id="prev-assistant-uuid"))

        calls = mock_db.save_conversation.call_args_list
        # First call (user turn) links to parent conversation entry
        user_call_kwargs = calls[0][1]
        assert user_call_kwargs["reply_to_id"] == "prev-assistant-uuid"
        # Second call (assistant turn) links to user turn UUID
        assistant_call_kwargs = calls[1][1]
        assert assistant_call_kwargs["reply_to_id"] == "user-turn-uuid"

    @patch("telegram_bot.flow_callbacks._db")
    def test_save_turn_channel_detection_dm(self, mock_db):
        mock_db.save_conversation.return_value = "uuid"
        msg = _make_message(chat_type="private")
        sent = _make_sent()

        asyncio.run(_save_turn(msg, sent, "q", "a", {}))

        user_call_kwargs = mock_db.save_conversation.call_args_list[0][1]
        assert user_call_kwargs["metadata"]["channel"] == "dm"

    @patch("telegram_bot.flow_callbacks._db")
    def test_save_turn_channel_detection_group(self, mock_db):
        mock_db.save_conversation.return_value = "uuid"
        msg = _make_message(chat_type="group")
        sent = _make_sent()

        asyncio.run(_save_turn(msg, sent, "q", "a", {}))

        user_call_kwargs = mock_db.save_conversation.call_args_list[0][1]
        assert user_call_kwargs["metadata"]["channel"] == "group"

    @patch("telegram_bot.flow_callbacks._db")
    def test_save_turn_db_error_silenced(self, mock_db):
        mock_db.save_conversation.side_effect = RuntimeError("db down")
        msg = _make_message()
        sent = _make_sent()

        # Should not raise
        asyncio.run(_save_turn(msg, sent, "q", "a", {}))

    @patch("telegram_bot.flow_callbacks._db")
    def test_save_turn_metadata_merged_with_channel(self, mock_db):
        mock_db.save_conversation.return_value = "uuid"
        msg = _make_message(chat_type="supergroup")
        sent = _make_sent()

        asyncio.run(_save_turn(msg, sent, "q", "a", {"command": "support"}))

        user_call_kwargs = mock_db.save_conversation.call_args_list[0][1]
        meta = user_call_kwargs["metadata"]
        assert meta["command"] == "support"
        assert meta["channel"] == "group"


# ===================================================================
#  _send_html()
# ===================================================================

class TestSendHtml:

    def test_send_html_returns_message(self):
        fake_response = MagicMock()
        msg = AsyncMock()
        msg.answer.return_value = fake_response

        result = asyncio.run(_send_html(msg, "hello"))

        assert result is fake_response


# ===================================================================
#  _format_reply_chain()
# ===================================================================

class TestFormatReplyChain:

    def test_single_entry(self):
        chain = [{"role": "assistant", "content": "Привет!"}]
        assert _format_reply_chain(chain) == "assistant: Привет!"

    def test_multi_turn(self):
        chain = [
            {"role": "user", "content": "Привет"},
            {"role": "assistant", "content": "Здравствуйте!"},
            {"role": "user", "content": "Как дела?"},
        ]
        expected = "user: Привет\nassistant: Здравствуйте!\nuser: Как дела?"
        assert _format_reply_chain(chain) == expected

    def test_empty_chain(self):
        assert _format_reply_chain([]) == ""


# ===================================================================
#  _handle_nl_reply()
# ===================================================================

def _make_nl_message(
    chat_id=100, user_id=42, message_id=10, text="Какой курс?",
    reply_message_id=9, reply_text="Предыдущий ответ бота",
    reply_from_bot=True, chat_type="private",
):
    msg = AsyncMock()
    msg.chat.id = chat_id
    msg.chat.type = chat_type
    msg.from_user.id = user_id
    msg.message_id = message_id
    msg.text = text

    reply = MagicMock()
    reply.message_id = reply_message_id
    reply.text = reply_text
    reply.from_user = MagicMock()
    reply.from_user.is_bot = reply_from_bot
    msg.reply_to_message = reply
    return msg


def _make_state(active=False):
    state = AsyncMock()
    state.get_state.return_value = "SomeState:step" if active else None
    return state


class TestHandleNlReply:

    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_happy_path_with_db_conversation(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot,
    ):
        msg = _make_nl_message()
        state = _make_state()

        # DB returns a conversation entry
        mock_db.get_conversation_by_message_id.return_value = {
            "id": "conv-uuid-1",
            "role": "assistant",
            "content": "Предыдущий ответ",
        }
        mock_db.get_reply_chain.return_value = [
            {"role": "user", "content": "Первый вопрос"},
            {"role": "assistant", "content": "Предыдущий ответ"},
        ]

        # Retriever
        retriever = MagicMock()
        retriever.get_core.return_value = "core knowledge"
        retriever.retrieve.return_value = "relevant knowledge"
        mock_get_retriever.return_value = retriever

        # Gemini
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "Ответ бота"}
        mock_gemini_cls.return_value = mock_gemini

        # Send
        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        mock_db.get_conversation_by_message_id.assert_called_once_with(100, 9)
        mock_db.get_reply_chain.assert_called_once_with("conv-uuid-1", depth=10)
        mock_gemini.call.assert_called_once()
        mock_send_html.assert_awaited_once()
        # Verify reply_to_message_id kwarg
        send_kwargs = mock_send_html.call_args
        assert send_kwargs[1]["reply_to_message_id"] == 10
        mock_save_turn.assert_awaited_once()
        # Verify parent_id is passed to link conversation chain
        save_kwargs = mock_save_turn.call_args[1]
        assert save_kwargs["parent_id"] == "conv-uuid-1"

    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_no_db_record_bootstraps_from_reply_text(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot,
    ):
        msg = _make_nl_message(text="Расскажи подробнее", reply_text="Вот информация")
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = None

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = "knowledge"
        mock_get_retriever.return_value = retriever

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "Подробности"}
        mock_gemini_cls.return_value = mock_gemini

        sent_msg = MagicMock()
        mock_send_html.return_value = sent_msg

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        mock_db.get_reply_chain.assert_not_called()
        # Verify the history was bootstrapped
        call_args = mock_gemini.call.call_args[0]
        prompt = call_args[0]
        assert "assistant: Вот информация" in prompt
        assert "user: Расскажи подробнее" in prompt
        # No DB record → parent_id is None
        save_kwargs = mock_save_turn.call_args[1]
        assert save_kwargs["parent_id"] is None

    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_llm_error_returns_false(
        self, mock_db, mock_get_retriever, mock_gemini_cls, mock_bot,
    ):
        msg = _make_nl_message()
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = None

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = ""
        mock_get_retriever.return_value = retriever

        mock_gemini = MagicMock()
        mock_gemini.call.side_effect = RuntimeError("Gemini down")
        mock_gemini_cls.return_value = mock_gemini

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is False

    def test_fsm_state_active_returns_false(self):
        msg = _make_nl_message()
        state = _make_state(active=True)

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is False

    def test_no_reply_returns_false(self):
        msg = AsyncMock()
        msg.reply_to_message = None
        state = _make_state()

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is False

    def test_reply_not_from_bot_returns_false(self):
        msg = _make_nl_message(reply_from_bot=False)
        state = _make_state()

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is False

    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_reply_chain_formatting_in_history(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot,
    ):
        msg = _make_nl_message(text="Третий вопрос")
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = {"id": "conv-3"}
        mock_db.get_reply_chain.return_value = [
            {"role": "user", "content": "Первый вопрос"},
            {"role": "assistant", "content": "Первый ответ"},
            {"role": "user", "content": "Второй вопрос"},
            {"role": "assistant", "content": "Второй ответ"},
        ]

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = ""
        mock_get_retriever.return_value = retriever

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "Третий ответ"}
        mock_gemini_cls.return_value = mock_gemini

        sent_msg = MagicMock()
        mock_send_html.return_value = sent_msg

        asyncio.run(_handle_nl_reply(msg, state))

        prompt = mock_gemini.call.call_args[0][0]
        assert "user: Первый вопрос" in prompt
        assert "assistant: Первый ответ" in prompt
        assert "user: Второй вопрос" in prompt
        assert "assistant: Второй ответ" in prompt
        assert "user: Третий вопрос" in prompt

    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_long_answer_truncated(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot,
    ):
        msg = _make_nl_message()
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = None

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = ""
        mock_get_retriever.return_value = retriever

        long_answer = "x" * 5000
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": long_answer}
        mock_gemini_cls.return_value = mock_gemini

        sent_msg = MagicMock()
        mock_send_html.return_value = sent_msg

        asyncio.run(_handle_nl_reply(msg, state))

        # Check the text sent is truncated to 4000
        sent_text = mock_send_html.call_args[0][1]
        assert len(sent_text) == 4000


# ===================================================================
#  handle_admin_reply routing — legium forwarding priority
# ===================================================================

class TestAdminReplyRouting:

    @patch("telegram_bot.flow_callbacks._handle_nl_reply")
    def test_legium_forwarding_takes_priority(self, mock_nl_reply):
        """When _admin_reply_map has an entry, legium forwarding runs, NL reply is NOT called."""
        msg = AsyncMock()
        msg.chat.id = 100
        msg.text = "https://legium.io/doc/123"
        msg.from_user.id = 1

        reply = MagicMock()
        reply.message_id = 50
        msg.reply_to_message = reply

        state = _make_state()

        # Register in admin_reply_map
        _admin_reply_map[(100, 50)] = ("", "contractor-1")

        with patch("telegram_bot.flow_callbacks.update_legium_link"):
            asyncio.run(handle_admin_reply(msg, state))

        mock_nl_reply.assert_not_awaited()

        # Clean up
        _admin_reply_map.pop((100, 50), None)

    @patch("telegram_bot.flow_callbacks._handle_nl_reply")
    def test_nl_reply_called_when_no_legium_entry(self, mock_nl_reply):
        """When _admin_reply_map has no entry, NL reply fallback is called."""
        msg = AsyncMock()
        msg.chat.id = 200
        msg.text = "Какой вопрос"

        reply = MagicMock()
        reply.message_id = 60
        msg.reply_to_message = reply

        state = _make_state()

        asyncio.run(handle_admin_reply(msg, state))

        mock_nl_reply.assert_awaited_once_with(msg, state)

    def test_no_reply_message_returns_early(self):
        msg = AsyncMock()
        msg.reply_to_message = None
        state = _make_state()

        # Should not raise
        asyncio.run(handle_admin_reply(msg, state))


# ===================================================================
#  _handle_draft_reply()
# ===================================================================

def _make_draft(uid="uid-1", from_addr="user@example.com", reply_to="") -> SupportDraft:
    email = IncomingEmail(
        uid=uid, from_addr=from_addr, to_addr="support@republic.ru",
        reply_to=reply_to, subject="Help", body="I need help", date="2026-03-01",
    )
    return SupportDraft(email=email, can_answer=True, draft_reply="Draft text")


class TestHandleDraftReply:

    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._inbox")
    def test_replacement_path(self, mock_inbox, mock_get_retriever):
        draft = _make_draft(reply_to="user@example.com")
        mock_inbox.get_pending_support.return_value = draft

        msg = AsyncMock()
        msg.text = "Здравствуйте, вот ваш ответ."
        msg.message_id = 10

        asyncio.run(_handle_draft_reply(msg, "uid-1"))

        mock_inbox.update_and_approve_support.assert_called_once_with("uid-1", msg.text)
        msg.reply.assert_awaited_once()
        reply_text = msg.reply.call_args[0][0]
        assert "user@example.com" in reply_text
        assert reply_text == replies.tech_support.replacement_sent.format(addr="user@example.com")

    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._inbox")
    def test_teaching_feedback_path(self, mock_inbox, mock_get_retriever):
        draft = _make_draft()
        mock_inbox.get_pending_support.return_value = draft

        retriever = MagicMock()
        mock_get_retriever.return_value = retriever

        msg = AsyncMock()
        msg.text = "Не отвечай на такие письма"
        msg.message_id = 10

        asyncio.run(_handle_draft_reply(msg, "uid-1"))

        mock_inbox.skip_support.assert_called_once_with("uid-1")
        retriever.store_feedback.assert_called_once_with(
            "Не отвечай на такие письма", scope="tech_support",
        )
        msg.reply.assert_awaited_once_with(replies.tech_support.feedback_noted)

    @patch("telegram_bot.flow_callbacks._inbox")
    def test_expired_draft(self, mock_inbox):
        mock_inbox.get_pending_support.return_value = None

        msg = AsyncMock()
        msg.text = "Some reply"

        asyncio.run(_handle_draft_reply(msg, "uid-gone"))

        msg.reply.assert_awaited_once_with(replies.tech_support.expired)
        mock_inbox.update_and_approve_support.assert_not_called()
        mock_inbox.skip_support.assert_not_called()

    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._inbox")
    def test_greeting_prefixes_case_insensitive(self, mock_inbox, mock_get_retriever):
        draft = _make_draft(reply_to="addr@test.com")
        mock_inbox.get_pending_support.return_value = draft

        for greeting in ("ДОБРЫЙ ДЕНЬ, текст", "Hello, how are you", "dear sender, info", "Hi, вот ответ"):
            mock_inbox.reset_mock()
            msg = AsyncMock()
            msg.text = greeting
            msg.message_id = 10

            asyncio.run(_handle_draft_reply(msg, "uid-1"))

            mock_inbox.update_and_approve_support.assert_called_once(), \
                f"Expected replacement path for greeting: {greeting!r}"

    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._inbox")
    def test_store_feedback_failure_still_replies(self, mock_inbox, mock_get_retriever):
        draft = _make_draft()
        mock_inbox.get_pending_support.return_value = draft

        retriever = MagicMock()
        retriever.store_feedback.side_effect = RuntimeError("embedding service down")
        mock_get_retriever.return_value = retriever

        msg = AsyncMock()
        msg.text = "Не отвечай на это"
        msg.message_id = 10

        asyncio.run(_handle_draft_reply(msg, "uid-1"))

        mock_inbox.skip_support.assert_called_once_with("uid-1")
        msg.reply.assert_awaited_once_with(replies.tech_support.feedback_noted)

    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._inbox")
    def test_replacement_uses_from_addr_when_no_reply_to(self, mock_inbox, mock_get_retriever):
        draft = _make_draft(from_addr="fallback@test.com", reply_to="")
        mock_inbox.get_pending_support.return_value = draft

        msg = AsyncMock()
        msg.text = "Привет, вот ответ"
        msg.message_id = 10

        asyncio.run(_handle_draft_reply(msg, "uid-1"))

        reply_text = msg.reply.call_args[0][0]
        assert "fallback@test.com" in reply_text


# ===================================================================
#  _send_support_draft registers in _support_draft_map
# ===================================================================

class TestSendSupportDraftMap:

    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    def test_send_support_draft_populates_map(self, mock_bot):
        from telegram_bot.flow_callbacks import _send_support_draft

        draft = _make_draft(uid="email-uid-42")

        sent = AsyncMock()
        sent.message_id = 99
        mock_bot.send_message.return_value = sent

        admin_id = 777
        asyncio.run(_send_support_draft(admin_id, draft))

        assert _support_draft_map.get((777, 99)) == "email-uid-42"

        # Clean up
        _support_draft_map.pop((777, 99), None)


# ===================================================================
#  handle_admin_reply routing — support draft priority
# ===================================================================

class TestAdminReplySupportDraftRouting:

    @patch("telegram_bot.flow_callbacks._handle_nl_reply")
    @patch("telegram_bot.flow_callbacks._handle_draft_reply")
    def test_support_draft_route(self, mock_draft_reply, mock_nl_reply):
        msg = AsyncMock()
        msg.chat.id = 300
        msg.text = "Здравствуйте, вот ответ"

        reply = MagicMock()
        reply.message_id = 70
        msg.reply_to_message = reply

        state = _make_state()

        _support_draft_map[(300, 70)] = "uid-42"

        asyncio.run(handle_admin_reply(msg, state))

        mock_draft_reply.assert_awaited_once_with(msg, "uid-42")
        mock_nl_reply.assert_not_awaited()
        # Map entry cleaned up
        assert (300, 70) not in _support_draft_map

    @patch("telegram_bot.flow_callbacks._handle_nl_reply")
    @patch("telegram_bot.flow_callbacks._handle_draft_reply")
    def test_legium_still_has_priority_over_support_draft(self, mock_draft_reply, mock_nl_reply):
        msg = AsyncMock()
        msg.chat.id = 400
        msg.text = "https://legium.io/doc/999"
        msg.from_user.id = 1

        reply = MagicMock()
        reply.message_id = 80
        msg.reply_to_message = reply

        state = _make_state()

        # Both maps have an entry for the same key
        _admin_reply_map[(400, 80)] = ("", "contractor-1")
        _support_draft_map[(400, 80)] = "uid-99"

        with patch("telegram_bot.flow_callbacks.update_legium_link"):
            asyncio.run(handle_admin_reply(msg, state))

        # Legium handled it, draft reply was NOT called
        mock_draft_reply.assert_not_awaited()
        mock_nl_reply.assert_not_awaited()

        # Clean up
        _admin_reply_map.pop((400, 80), None)
        _support_draft_map.pop((400, 80), None)
