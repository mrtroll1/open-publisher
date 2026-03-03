"""Tests for Phase 7: Admin Teaching — /teach, NL teaching detection,
/knowledge, /forget, /kedit commands.

All external dependencies are mocked — no real network calls.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _make_message(text: str = "", chat_id: int = 100, user_id: int = 42) -> AsyncMock:
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.message_id = 10
    msg.reply_to_message = None
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    return msg


def _make_state(active=False) -> AsyncMock:
    state = AsyncMock()
    state.get_state.return_value = "SomeState:step" if active else None
    return state


def _make_nl_message(
    text="Какой курс?", reply_text="Предыдущий ответ бота",
    reply_from_bot=True,
):
    msg = AsyncMock()
    msg.chat.id = 100
    msg.chat.type = "private"
    msg.from_user.id = 42
    msg.message_id = 10
    msg.text = text

    reply = MagicMock()
    reply.message_id = 9
    reply.text = reply_text
    reply.from_user = MagicMock()
    reply.from_user.is_bot = reply_from_bot
    msg.reply_to_message = reply
    return msg


# ===================================================================
#  KnowledgeRetriever.store_teaching
# ===================================================================

@patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
@patch("backend.domain.services.knowledge_retriever.EmbeddingGateway")
@patch("backend.domain.services.knowledge_retriever.DbGateway")
def _make_retriever(MockDb, MockEmbed):
    from backend.domain.services.knowledge_retriever import KnowledgeRetriever
    kr = KnowledgeRetriever()
    return kr, kr._db, kr._embed


class TestStoreTeaching:

    def test_happy_path(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1, 0.2, 0.3]
        mock_db.save_knowledge_entry.return_value = "teach-uuid-1"

        result = kr.store_teaching("Всегда отвечай на русском")

        assert result == "teach-uuid-1"
        mock_embed.embed_one.assert_called_once_with("Всегда отвечай на русском")
        mock_db.save_knowledge_entry.assert_called_once_with(
            tier="domain",
            scope="general",
            title="Всегда отвечай на русском",
            content="Всегда отвечай на русском",
            source="admin_teach",
            embedding=[0.1, 0.2, 0.3],
        )

    def test_custom_scope(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.save_knowledge_entry.return_value = "uuid"

        kr.store_teaching("billing rule", scope="billing")

        call_kwargs = mock_db.save_knowledge_entry.call_args[1]
        assert call_kwargs["scope"] == "billing"
        assert call_kwargs["source"] == "admin_teach"

    def test_title_truncated_at_60_chars(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.save_knowledge_entry.return_value = "uuid"

        long_text = "А" * 100
        kr.store_teaching(long_text)

        call_kwargs = mock_db.save_knowledge_entry.call_args[1]
        assert len(call_kwargs["title"]) == 60
        assert call_kwargs["content"] == long_text


# ===================================================================
#  cmd_teach
# ===================================================================

class TestCmdTeach:

    @patch("telegram_bot.flow_callbacks._classify_teaching_text", new_callable=AsyncMock, return_value=("general", "domain"))
    @patch("telegram_bot.flow_callbacks._get_retriever")
    def test_stores_entry_and_replies(self, mock_get_retriever, mock_classify):
        from telegram_bot.flow_callbacks import cmd_teach

        retriever = MagicMock()
        retriever.store_teaching.return_value = "new-id"
        mock_get_retriever.return_value = retriever

        msg = _make_message("/teach Клиентов зовут по имени")
        state = _make_state()

        asyncio.run(cmd_teach(msg, state))

        mock_classify.assert_awaited_once_with("Клиентов зовут по имени")
        retriever.store_teaching.assert_called_once_with("Клиентов зовут по имени", scope="general", tier="domain")
        msg.answer.assert_awaited_once()
        reply_text = msg.answer.call_args[0][0]
        assert "Запомнил" in reply_text
        assert "general" in reply_text

    def test_no_text_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_teach

        msg = _make_message("/teach")
        state = _make_state()

        asyncio.run(cmd_teach(msg, state))

        msg.answer.assert_awaited_once()
        assert "/teach" in msg.answer.call_args[0][0]

    def test_whitespace_only_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_teach

        msg = _make_message("/teach   ")
        state = _make_state()

        asyncio.run(cmd_teach(msg, state))

        msg.answer.assert_awaited_once()
        assert "/teach" in msg.answer.call_args[0][0]

    @patch("telegram_bot.flow_callbacks._classify_teaching_text", new_callable=AsyncMock, return_value=("tech_support", "domain"))
    @patch("telegram_bot.flow_callbacks._get_retriever")
    def test_stores_with_correct_source(self, mock_get_retriever, mock_classify):
        """Verify the retriever's store_teaching (source=admin_teach) is called, not store_feedback."""
        from telegram_bot.flow_callbacks import cmd_teach

        retriever = MagicMock()
        retriever.store_teaching.return_value = "id"
        mock_get_retriever.return_value = retriever

        msg = _make_message("/teach Важное правило")
        state = _make_state()

        asyncio.run(cmd_teach(msg, state))

        retriever.store_teaching.assert_called_once()
        retriever.store_feedback.assert_not_called()


# ===================================================================
#  NL teaching detection in _handle_nl_reply
# ===================================================================

class TestNlTeachingDetection:

    @patch("telegram_bot.flow_callbacks._classify_teaching_text", new_callable=AsyncMock, return_value=("general", "domain"))
    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_zapomni_triggers_store(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot, mock_classify,
    ):
        from telegram_bot.flow_callbacks import _handle_nl_reply

        msg = _make_nl_message(text="Запомни: клиентам отвечаем на русском")
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = None

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = ""
        retriever.store_teaching.return_value = "id"
        mock_get_retriever.return_value = retriever

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "Хорошо, запомнил"}
        mock_gemini_cls.return_value = mock_gemini

        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        retriever.store_teaching.assert_called_once_with(
            "Запомни: клиентам отвечаем на русском", scope="general", tier="domain",
        )

    @patch("telegram_bot.flow_callbacks._classify_teaching_text", new_callable=AsyncMock, return_value=("tech_support", "domain"))
    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_uchti_triggers_store(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot, mock_classify,
    ):
        from telegram_bot.flow_callbacks import _handle_nl_reply

        msg = _make_nl_message(text="Учти, что подписки стоят 500 рублей")
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = None

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = ""
        retriever.store_teaching.return_value = "id"
        mock_get_retriever.return_value = retriever

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "Понял"}
        mock_gemini_cls.return_value = mock_gemini

        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        retriever.store_teaching.assert_called_once()

    @patch("telegram_bot.flow_callbacks._classify_teaching_text", new_callable=AsyncMock, return_value=("general", "domain"))
    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_imey_v_vidu_triggers_store(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot, mock_classify,
    ):
        from telegram_bot.flow_callbacks import _handle_nl_reply

        msg = _make_nl_message(text="Имей в виду, что мы не работаем по выходным")
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = None

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = ""
        retriever.store_teaching.return_value = "id"
        mock_get_retriever.return_value = retriever

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "Понял"}
        mock_gemini_cls.return_value = mock_gemini

        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        retriever.store_teaching.assert_called_once()

    @patch("telegram_bot.flow_callbacks._classify_teaching_text", new_callable=AsyncMock, return_value=("general", "domain"))
    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_remember_triggers_store(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot, mock_classify,
    ):
        from telegram_bot.flow_callbacks import _handle_nl_reply

        msg = _make_nl_message(text="Remember that articles go live on Mondays")
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = None

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = ""
        retriever.store_teaching.return_value = "id"
        mock_get_retriever.return_value = retriever

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "OK"}
        mock_gemini_cls.return_value = mock_gemini

        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        retriever.store_teaching.assert_called_once()

    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_no_keyword_no_store(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot,
    ):
        from telegram_bot.flow_callbacks import _handle_nl_reply

        msg = _make_nl_message(text="Какая погода завтра?")
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = None

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = ""
        mock_get_retriever.return_value = retriever

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "Не знаю"}
        mock_gemini_cls.return_value = mock_gemini

        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        retriever.store_teaching.assert_not_called()

    @patch("telegram_bot.flow_callbacks._classify_teaching_text", new_callable=AsyncMock, return_value=("general", "domain"))
    @patch("telegram_bot.flow_callbacks.bot", new_callable=AsyncMock)
    @patch("telegram_bot.flow_callbacks._send_html")
    @patch("telegram_bot.flow_callbacks._save_turn")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_store_failure_does_not_break_reply(
        self, mock_db, mock_get_retriever, mock_gemini_cls,
        mock_save_turn, mock_send_html, mock_bot, mock_classify,
    ):
        """Even if store_teaching raises, the NL reply flow should continue."""
        from telegram_bot.flow_callbacks import _handle_nl_reply

        msg = _make_nl_message(text="Запомни это правило")
        state = _make_state()

        mock_db.get_conversation_by_message_id.return_value = None

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = ""
        retriever.store_teaching.side_effect = Exception("DB down")
        mock_get_retriever.return_value = retriever

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "Ок"}
        mock_gemini_cls.return_value = mock_gemini

        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        mock_gemini.call.assert_called_once()


# ===================================================================
#  cmd_knowledge
# ===================================================================

class TestCmdKnowledge:

    @patch("telegram_bot.flow_callbacks._db")
    def test_lists_all_entries(self, mock_db):
        from telegram_bot.flow_callbacks import cmd_knowledge

        mock_db.list_knowledge.return_value = [
            {
                "id": "uuid-1", "tier": "domain", "scope": "general",
                "title": "Правило 1", "content": "Содержание 1",
                "source": "admin_teach", "created_at": datetime(2025, 6, 15),
            },
            {
                "id": "uuid-2", "tier": "core", "scope": "tech_support",
                "title": "Правило 2", "content": "Содержание 2",
                "source": "admin_feedback", "created_at": datetime(2025, 7, 1),
            },
        ]

        msg = _make_message("/knowledge")
        state = _make_state()

        asyncio.run(cmd_knowledge(msg, state))

        mock_db.list_knowledge.assert_called_once_with(scope=None, tier=None)
        msg.answer.assert_awaited_once()
        reply = msg.answer.call_args[0][0]
        # Default mode: no IDs shown
        assert "uuid-1" not in reply
        assert "Правило 1" in reply
        assert "2025-06-15" in reply

    @patch("telegram_bot.flow_callbacks._db")
    def test_verbose_shows_ids_and_content(self, mock_db):
        from telegram_bot.flow_callbacks import cmd_knowledge

        mock_db.list_knowledge.return_value = [
            {
                "id": "uuid-1", "tier": "domain", "scope": "general",
                "title": "Правило 1", "content": "Содержание 1",
                "source": "admin_teach", "created_at": datetime(2025, 6, 15),
            },
        ]

        msg = _make_message("/knowledge -v")
        state = _make_state()

        asyncio.run(cmd_knowledge(msg, state))

        mock_db.list_knowledge.assert_called_once_with(scope=None, tier=None)
        reply = msg.answer.call_args[0][0]
        assert "uuid-1" in reply
        assert "Содержание 1" in reply

    @patch("telegram_bot.flow_callbacks._db")
    def test_filters_by_scope(self, mock_db):
        from telegram_bot.flow_callbacks import cmd_knowledge

        mock_db.list_knowledge.return_value = []

        msg = _make_message("/knowledge tech_support")
        state = _make_state()

        asyncio.run(cmd_knowledge(msg, state))

        mock_db.list_knowledge.assert_called_once_with(scope="tech_support", tier=None)

    @patch("telegram_bot.flow_callbacks._db")
    def test_filters_by_scope_and_tier(self, mock_db):
        from telegram_bot.flow_callbacks import cmd_knowledge

        mock_db.list_knowledge.return_value = []

        msg = _make_message("/knowledge tech_support core")
        state = _make_state()

        asyncio.run(cmd_knowledge(msg, state))

        mock_db.list_knowledge.assert_called_once_with(scope="tech_support", tier="core")

    @patch("telegram_bot.flow_callbacks._db")
    def test_empty_list(self, mock_db):
        from telegram_bot.flow_callbacks import cmd_knowledge

        mock_db.list_knowledge.return_value = []

        msg = _make_message("/knowledge")
        state = _make_state()

        asyncio.run(cmd_knowledge(msg, state))

        msg.answer.assert_awaited_once()
        reply = msg.answer.call_args[0][0]
        assert "не найдено" in reply.lower()


# ===================================================================
#  cmd_forget
# ===================================================================

class TestCmdForget:

    @patch("telegram_bot.flow_callbacks._db")
    def test_soft_deletes_entry(self, mock_db):
        from telegram_bot.flow_callbacks import cmd_forget

        mock_db.deactivate_knowledge.return_value = True

        msg = _make_message("/forget uuid-123")
        state = _make_state()

        asyncio.run(cmd_forget(msg, state))

        mock_db.deactivate_knowledge.assert_called_once_with("uuid-123")
        msg.answer.assert_awaited_once()
        reply = msg.answer.call_args[0][0]
        assert "удалена" in reply.lower()

    @patch("telegram_bot.flow_callbacks._db")
    def test_nonexistent_id_reports_not_found(self, mock_db):
        from telegram_bot.flow_callbacks import cmd_forget

        mock_db.deactivate_knowledge.return_value = False

        msg = _make_message("/forget uuid-nonexistent")
        state = _make_state()

        asyncio.run(cmd_forget(msg, state))

        mock_db.deactivate_knowledge.assert_called_once_with("uuid-nonexistent")
        msg.answer.assert_awaited_once()
        reply = msg.answer.call_args[0][0]
        assert "не найдена" in reply.lower()

    def test_no_id_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_forget

        msg = _make_message("/forget")
        state = _make_state()

        asyncio.run(cmd_forget(msg, state))

        msg.answer.assert_awaited_once()
        assert "/forget" in msg.answer.call_args[0][0]

    @patch("telegram_bot.flow_callbacks._db")
    def test_db_error_reports_not_found(self, mock_db):
        from telegram_bot.flow_callbacks import cmd_forget

        mock_db.deactivate_knowledge.side_effect = Exception("not found")

        msg = _make_message("/forget bad-id")
        state = _make_state()

        asyncio.run(cmd_forget(msg, state))

        msg.answer.assert_awaited_once()
        reply = msg.answer.call_args[0][0]
        assert "не найдена" in reply.lower()


# ===================================================================
#  cmd_kedit
# ===================================================================

class TestCmdKedit:

    @patch("telegram_bot.flow_callbacks._get_retriever")
    @patch("telegram_bot.flow_callbacks._db")
    def test_updates_entry(self, mock_db, mock_get_retriever):
        from telegram_bot.flow_callbacks import cmd_kedit

        retriever = MagicMock()
        retriever._embed.embed_one.return_value = [0.9, 0.8]
        mock_get_retriever.return_value = retriever
        mock_db.update_knowledge_entry.return_value = True

        msg = _make_message("/kedit uuid-1 Новое содержание записи")
        state = _make_state()

        asyncio.run(cmd_kedit(msg, state))

        retriever._embed.embed_one.assert_called_once_with("Новое содержание записи")
        mock_db.update_knowledge_entry.assert_called_once_with(
            "uuid-1", "Новое содержание записи", [0.9, 0.8],
        )
        msg.answer.assert_awaited_once()
        reply = msg.answer.call_args[0][0]
        assert "обновлена" in reply.lower()

    def test_no_args_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_kedit

        msg = _make_message("/kedit")
        state = _make_state()

        asyncio.run(cmd_kedit(msg, state))

        msg.answer.assert_awaited_once()
        assert "/kedit" in msg.answer.call_args[0][0]

    def test_only_id_no_content_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_kedit

        msg = _make_message("/kedit uuid-1")
        state = _make_state()

        asyncio.run(cmd_kedit(msg, state))

        msg.answer.assert_awaited_once()
        assert "/kedit" in msg.answer.call_args[0][0]


# ===================================================================
#  flows.py registration
# ===================================================================

class TestFlowsRegistration:

    def test_teach_command_registered(self):
        from telegram_bot.flows import admin_commands
        commands = {c.command for c in admin_commands}
        assert "teach" in commands

    def test_knowledge_command_registered(self):
        from telegram_bot.flows import admin_commands
        commands = {c.command for c in admin_commands}
        assert "knowledge" in commands

    def test_forget_command_registered(self):
        from telegram_bot.flows import admin_commands
        commands = {c.command for c in admin_commands}
        assert "forget" in commands

    def test_kedit_command_registered(self):
        from telegram_bot.flows import admin_commands
        commands = {c.command for c in admin_commands}
        assert "kedit" in commands

    def test_not_in_group_handlers(self):
        """Teaching commands should NOT be in group command handlers."""
        from telegram_bot.flow_callbacks import _GROUP_COMMAND_HANDLERS
        for cmd in ("teach", "knowledge", "forget", "kedit"):
            assert cmd not in _GROUP_COMMAND_HANDLERS
