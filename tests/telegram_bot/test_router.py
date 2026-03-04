import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_bot.router import (
    _DM_COMMANDS,
    _ADMIN_COMMANDS,
    _FSM_HANDLERS,
    _FSM_TRANSITIONS,
    _FSM_ENTRY_MESSAGES,
    ContractorStates,
)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _make_message(text="", chat_id=100, user_id=42, chat_type="private") -> AsyncMock:
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.chat.type = chat_type
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.message_id = 10
    msg.reply_to_message = None
    msg.answer = AsyncMock()
    msg.bot = AsyncMock()
    return msg


def _make_state(current=None) -> AsyncMock:
    state = AsyncMock()
    state.get_state.return_value = current
    return state


# ===================================================================
#  Registries
# ===================================================================

class TestRegistries:

    def test_dm_commands_has_expected_keys(self):
        expected = {"start", "menu", "sign_doc", "update_payment_data", "manage_redirects"}
        assert set(_DM_COMMANDS.keys()) == expected

    def test_admin_commands_has_expected_keys(self):
        expected = {
            "generate", "generate_invoices", "send_global_invoices", "send_legium_links",
            "orphan_contractors", "articles", "lookup", "budget",
            "upload_to_airtable", "sync_entities", "ingest_articles", "extract_knowledge",
            "chatid", "health", "support", "code",
            "nl", "teach", "knowledge", "ksearch", "forget", "kedit",
            "env", "env_edit", "env_bind", "env_create", "env_unbind",
            "entity", "entity_add", "entity_link", "entity_note",
        }
        assert set(_ADMIN_COMMANDS.keys()) == expected

    def test_fsm_handlers_has_expected_keys(self):
        expected = {
            "lookup", "waiting_verification", "waiting_type",
            "waiting_data", "waiting_amount", "waiting_update_data",
            "waiting_editor_source_name",
        }
        assert set(_FSM_HANDLERS.keys()) == expected

    def test_fsm_transitions_has_expected_keys(self):
        expected = {
            ("lookup", "register"),
            ("waiting_verification", "verified"),
            ("waiting_verification", "invoice"),
            ("waiting_type", "valid"),
            ("waiting_data", "complete"),
            ("waiting_data", "invoice"),
            ("waiting_amount", "done"),
            ("waiting_update_data", "done"),
            ("waiting_editor_source_name", "done"),
        }
        assert set(_FSM_TRANSITIONS.keys()) == expected

    def test_fsm_entry_messages_has_expected_keys(self):
        assert set(_FSM_ENTRY_MESSAGES.keys()) == {"waiting_type"}

    def test_all_fsm_handler_states_exist_on_contractor_states(self):
        for state_name in _FSM_HANDLERS:
            assert hasattr(ContractorStates, state_name)


# ===================================================================
#  _route_text — Group Messages
# ===================================================================

class TestRouteTextGroupMessages:

    @patch("telegram_bot.router.handle_group_message", new_callable=AsyncMock)
    @patch("telegram_bot.router.resolve_environment_record", return_value={"name": "editorial_group"})
    def test_bound_group_dispatches(self, mock_resolve, mock_group_handler):
        from telegram_bot.router import _route_text

        msg = _make_message("hello", chat_id=500, chat_type="supergroup")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_group_handler.assert_awaited_once()
        args = mock_group_handler.call_args
        assert args[0][0] is msg
        assert args[0][1] is state

    @patch("telegram_bot.router.handle_group_message", new_callable=AsyncMock)
    @patch("telegram_bot.router.resolve_environment_record", return_value=None)
    def test_unbound_group_returns_early(self, mock_resolve, mock_group_handler):
        from telegram_bot.router import _route_text

        msg = _make_message("hello", chat_id=999, chat_type="group")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_group_handler.assert_not_awaited()

    @patch("telegram_bot.router.handle_group_message", new_callable=AsyncMock)
    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router.resolve_environment_record", return_value=None)
    def test_group_message_does_not_fall_through_to_dm(self, mock_resolve, mock_contractor, mock_group):
        from telegram_bot.router import _route_text

        msg = _make_message("hello", chat_id=999, chat_type="group")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_contractor.assert_not_awaited()

    @patch("telegram_bot.router.cmd_env_bind", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=True)
    def test_env_bind_works_in_unbound_group(self, mock_is_admin, mock_env_bind):
        from telegram_bot.router import _route_text

        msg = _make_message("/env_bind editorial_group", chat_id=999, user_id=1, chat_type="group")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_env_bind.assert_awaited_once_with(msg, state)

    @patch("telegram_bot.router.cmd_env_unbind", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=True)
    def test_env_unbind_works_in_group(self, mock_is_admin, mock_env_unbind):
        from telegram_bot.router import _route_text

        msg = _make_message("/env_unbind", chat_id=500, user_id=1, chat_type="supergroup")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_env_unbind.assert_awaited_once_with(msg, state)

    @patch("telegram_bot.router.handle_group_message", new_callable=AsyncMock)
    @patch("telegram_bot.router.resolve_environment_record", return_value=None)
    @patch("telegram_bot.router.is_admin", return_value=False)
    def test_env_bind_rejected_for_non_admin_in_group(self, mock_is_admin, mock_resolve, mock_group_handler):
        from telegram_bot.router import _route_text

        msg = _make_message("/env_bind editorial_group", chat_id=999, user_id=42, chat_type="group")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_group_handler.assert_not_awaited()


# ===================================================================
#  _route_text — Commands
# ===================================================================

class TestRouteTextCommands:

    @patch("telegram_bot.router._DM_COMMANDS", {"start": AsyncMock()})
    def test_dm_command_dispatches(self):
        from telegram_bot.router import _route_text, _DM_COMMANDS

        msg = _make_message("/start", chat_type="private")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        _DM_COMMANDS["start"].assert_awaited_once_with(msg, state)

    @patch("telegram_bot.router._DM_COMMANDS", {"start": AsyncMock()})
    def test_dm_command_with_bot_suffix_stripped(self):
        from telegram_bot.router import _route_text, _DM_COMMANDS

        msg = _make_message("/start@republic_bot", chat_type="private")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        _DM_COMMANDS["start"].assert_awaited_once_with(msg, state)

    @patch("telegram_bot.router.is_admin", return_value=True)
    @patch("telegram_bot.router._ADMIN_COMMANDS", {"budget": AsyncMock()})
    @patch("telegram_bot.router._DM_COMMANDS", {})
    def test_admin_command_dispatches_for_admin(self, mock_is_admin):
        from telegram_bot.router import _route_text, _ADMIN_COMMANDS

        msg = _make_message("/budget 2026-01", chat_type="private", user_id=1)
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        _ADMIN_COMMANDS["budget"].assert_awaited_once_with(msg, state)

    @patch("telegram_bot.router.is_admin", return_value=False)
    @patch("telegram_bot.router._ADMIN_COMMANDS", {"budget": AsyncMock()})
    @patch("telegram_bot.router._DM_COMMANDS", {})
    def test_admin_command_skipped_for_non_admin(self, mock_is_admin):
        from telegram_bot.router import _route_text, _ADMIN_COMMANDS

        msg = _make_message("/budget 2026-01", chat_type="private", user_id=999)
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        _ADMIN_COMMANDS["budget"].assert_not_awaited()

    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router._DM_COMMANDS", {"start": AsyncMock()})
    def test_command_does_not_fall_through(self, mock_contractor):
        from telegram_bot.router import _route_text

        msg = _make_message("/start", chat_type="private")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_contractor.assert_not_awaited()

    @patch("telegram_bot.router.is_admin", return_value=True)
    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router._ADMIN_COMMANDS", {"budget": AsyncMock()})
    @patch("telegram_bot.router._DM_COMMANDS", {})
    def test_unknown_command_returns_without_catchall(self, mock_contractor, mock_is_admin):
        from telegram_bot.router import _route_text

        msg = _make_message("/nonexistent", chat_type="private")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_contractor.assert_not_awaited()

    @patch("telegram_bot.router.is_admin", return_value=True)
    @patch("telegram_bot.router._ADMIN_COMMANDS", {"budget": AsyncMock()})
    @patch("telegram_bot.router._DM_COMMANDS", {"budget": AsyncMock()})
    def test_dm_command_takes_priority_over_admin(self, mock_is_admin):
        from telegram_bot.router import _route_text, _DM_COMMANDS, _ADMIN_COMMANDS

        msg = _make_message("/budget", chat_type="private", user_id=1)
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        _DM_COMMANDS["budget"].assert_awaited_once()
        _ADMIN_COMMANDS["budget"].assert_not_awaited()


# ===================================================================
#  _route_text — Admin Reply
# ===================================================================

class TestRouteTextAdminReply:

    @patch("telegram_bot.router.handle_admin_reply", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=True)
    def test_admin_reply_dispatches(self, mock_is_admin, mock_admin_reply):
        from telegram_bot.router import _route_text

        msg = _make_message("reply text", chat_type="private", user_id=1)
        msg.reply_to_message = MagicMock()
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_admin_reply.assert_awaited_once_with(msg, state)

    @patch("telegram_bot.router.handle_admin_reply", new_callable=AsyncMock)
    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=False)
    def test_non_admin_reply_does_not_dispatch(self, mock_is_admin, mock_contractor, mock_admin_reply):
        from telegram_bot.router import _route_text

        msg = _make_message("reply text", chat_type="private", user_id=999)
        msg.reply_to_message = MagicMock()
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_admin_reply.assert_not_awaited()
        # Falls through to catch-all
        mock_contractor.assert_awaited_once()

    @patch("telegram_bot.router.handle_admin_reply", new_callable=AsyncMock)
    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=True)
    def test_admin_reply_does_not_fall_through(self, mock_is_admin, mock_contractor, mock_admin_reply):
        from telegram_bot.router import _route_text

        msg = _make_message("reply text", chat_type="private", user_id=1)
        msg.reply_to_message = MagicMock()
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_contractor.assert_not_awaited()


# ===================================================================
#  _route_text — FSM State
# ===================================================================

class TestRouteTextFsmState:

    @patch("telegram_bot.router._route_fsm", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=False)
    def test_active_state_dispatches_to_route_fsm(self, mock_is_admin, mock_route_fsm):
        from telegram_bot.router import _route_text

        msg = _make_message("some input", chat_type="private")
        state = _make_state(current="ContractorStates:waiting_type")

        asyncio.run(_route_text(msg, state))

        mock_route_fsm.assert_awaited_once_with(msg, state, "ContractorStates:waiting_type")

    @patch("telegram_bot.router._route_fsm", new_callable=AsyncMock)
    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=False)
    def test_active_state_does_not_fall_through(self, mock_is_admin, mock_contractor, mock_route_fsm):
        from telegram_bot.router import _route_text

        msg = _make_message("some input", chat_type="private")
        state = _make_state(current="ContractorStates:waiting_data")

        asyncio.run(_route_text(msg, state))

        mock_contractor.assert_not_awaited()


# ===================================================================
#  _route_text — Catch-All
# ===================================================================

class TestRouteTextCatchAll:

    @patch("telegram_bot.router._apply_fsm_transition", new_callable=AsyncMock)
    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=False)
    def test_free_text_dispatches_to_contractor(self, mock_is_admin, mock_contractor, mock_transition):
        from telegram_bot.router import _route_text

        mock_contractor.return_value = None
        msg = _make_message("hello", chat_type="private")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_contractor.assert_awaited_once_with(msg, state)
        msg.bot.send_chat_action.assert_awaited_once()

    @patch("telegram_bot.router._apply_fsm_transition", new_callable=AsyncMock)
    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=False)
    def test_free_text_applies_transition_on_result(self, mock_is_admin, mock_contractor, mock_transition):
        from telegram_bot.router import _route_text

        mock_contractor.return_value = "register"
        msg = _make_message("Иванов Иван", chat_type="private")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_transition.assert_awaited_once_with(msg, state, "lookup", "register")

    @patch("telegram_bot.router._apply_fsm_transition", new_callable=AsyncMock)
    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=False)
    def test_free_text_no_transition_on_none(self, mock_is_admin, mock_contractor, mock_transition):
        from telegram_bot.router import _route_text

        mock_contractor.return_value = None
        msg = _make_message("hello", chat_type="private")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        mock_transition.assert_not_awaited()

    @patch("telegram_bot.router._apply_fsm_transition", new_callable=AsyncMock)
    @patch("telegram_bot.router.handle_contractor_text", new_callable=AsyncMock)
    @patch("telegram_bot.router.is_admin", return_value=False)
    def test_sends_typing_before_contractor_text(self, mock_is_admin, mock_contractor, mock_transition):
        from telegram_bot.router import _route_text
        from aiogram.enums import ChatAction

        mock_contractor.return_value = None
        msg = _make_message("hello", chat_id=42, chat_type="private")
        state = _make_state()

        asyncio.run(_route_text(msg, state))

        msg.bot.send_chat_action.assert_awaited_once_with(42, ChatAction.TYPING)


# ===================================================================
#  _apply_fsm_transition
# ===================================================================

class TestApplyFsmTransition:

    def test_end_clears_state(self):
        from telegram_bot.router import _apply_fsm_transition

        msg = _make_message()
        state = _make_state()

        asyncio.run(_apply_fsm_transition(msg, state, "waiting_verification", "verified"))

        state.clear.assert_awaited_once()

    def test_end_with_message(self):
        from telegram_bot.router import _apply_fsm_transition, _FSM_TRANSITIONS

        msg = _make_message()
        state = _make_state()

        # ("waiting_verification", "verified") -> ("end", None) — no message
        asyncio.run(_apply_fsm_transition(msg, state, "waiting_verification", "verified"))

        msg.answer.assert_not_awaited()

    def test_target_sets_new_state(self):
        from telegram_bot.router import _apply_fsm_transition

        msg = _make_message()
        state = _make_state()

        # ("waiting_type", "valid") -> ("waiting_data", None)
        asyncio.run(_apply_fsm_transition(msg, state, "waiting_type", "valid"))

        state.set_state.assert_awaited_once()
        set_arg = state.set_state.call_args[0][0]
        assert set_arg == ContractorStates.waiting_data

    def test_transition_with_message(self):
        from telegram_bot.router import _apply_fsm_transition, _FSM_TRANSITIONS
        from telegram_bot import replies

        msg = _make_message()
        state = _make_state()

        # ("lookup", "register") -> ("waiting_type", replies.registration.begin)
        asyncio.run(_apply_fsm_transition(msg, state, "lookup", "register"))

        msg.answer.assert_awaited()
        assert msg.answer.call_args_list[0][0][0] == replies.registration.begin

    def test_transition_with_entry_message(self):
        from telegram_bot.router import _apply_fsm_transition
        from telegram_bot import replies

        msg = _make_message()
        state = _make_state()

        # ("lookup", "register") -> ("waiting_type", ...) and waiting_type has entry message
        asyncio.run(_apply_fsm_transition(msg, state, "lookup", "register"))

        # Should have 2 answer calls: transition message + entry message
        assert msg.answer.await_count == 2
        assert msg.answer.call_args_list[1][0][0] == replies.registration.type_prompt

    def test_no_transition_is_noop(self):
        from telegram_bot.router import _apply_fsm_transition

        msg = _make_message()
        state = _make_state()

        asyncio.run(_apply_fsm_transition(msg, state, "lookup", "nonexistent_key"))

        state.clear.assert_not_awaited()
        state.set_state.assert_not_awaited()
        msg.answer.assert_not_awaited()

    def test_end_does_not_set_state(self):
        from telegram_bot.router import _apply_fsm_transition

        msg = _make_message()
        state = _make_state()

        asyncio.run(_apply_fsm_transition(msg, state, "waiting_data", "complete"))

        state.set_state.assert_not_awaited()
        state.clear.assert_awaited_once()


# ===================================================================
#  _route_fsm
# ===================================================================

class TestRouteFsm:

    @patch("telegram_bot.router._apply_fsm_transition", new_callable=AsyncMock)
    @patch("telegram_bot.router._FSM_HANDLERS", {"waiting_type": AsyncMock(return_value="valid")})
    def test_dispatches_handler_and_applies_transition(self, mock_transition):
        from telegram_bot.router import _route_fsm, _FSM_HANDLERS

        msg = _make_message()
        state = _make_state()

        asyncio.run(_route_fsm(msg, state, "ContractorStates:waiting_type"))

        _FSM_HANDLERS["waiting_type"].assert_awaited_once_with(msg, state)
        mock_transition.assert_awaited_once_with(msg, state, "waiting_type", "valid")

    @patch("telegram_bot.router._apply_fsm_transition", new_callable=AsyncMock)
    @patch("telegram_bot.router._FSM_HANDLERS", {"waiting_type": AsyncMock(return_value=None)})
    def test_no_transition_on_none_result(self, mock_transition):
        from telegram_bot.router import _route_fsm

        msg = _make_message()
        state = _make_state()

        asyncio.run(_route_fsm(msg, state, "ContractorStates:waiting_type"))

        mock_transition.assert_not_awaited()

    @patch("telegram_bot.router._apply_fsm_transition", new_callable=AsyncMock)
    @patch("telegram_bot.router._FSM_HANDLERS", {})
    def test_unknown_state_returns_early(self, mock_transition):
        from telegram_bot.router import _route_fsm

        msg = _make_message()
        state = _make_state()

        asyncio.run(_route_fsm(msg, state, "ContractorStates:unknown_state"))

        mock_transition.assert_not_awaited()
        msg.bot.send_chat_action.assert_not_awaited()

    @patch("telegram_bot.router._apply_fsm_transition", new_callable=AsyncMock)
    @patch("telegram_bot.router._FSM_HANDLERS", {"waiting_data": AsyncMock(return_value="complete")})
    def test_sends_typing_action(self, mock_transition):
        from telegram_bot.router import _route_fsm
        from aiogram.enums import ChatAction

        msg = _make_message(chat_id=42)
        state = _make_state()

        asyncio.run(_route_fsm(msg, state, "ContractorStates:waiting_data"))

        msg.bot.send_chat_action.assert_awaited_once_with(42, ChatAction.TYPING)


# ===================================================================
#  register_all
# ===================================================================

class TestRegisterAll:

    def test_registers_correct_number_of_handlers(self):
        from telegram_bot.router import register_all

        dp = MagicMock()
        dp.callback_query = MagicMock()
        dp.callback_query.register = MagicMock()
        dp.message = MagicMock()
        dp.message.register = MagicMock()

        register_all(dp)

        assert dp.callback_query.register.call_count == 6
        assert dp.message.register.call_count == 3  # text + document + media

    def test_callback_handlers_match_source(self):
        from telegram_bot.router import register_all
        from telegram_bot.handlers.support_handlers import (
            handle_support_callback, handle_editorial_callback, handle_code_rate_callback,
        )
        from telegram_bot.handlers.contractor_handlers import (
            handle_duplicate_callback, handle_editor_source_callback, handle_linked_menu_callback,
        )

        dp = MagicMock()
        dp.callback_query = MagicMock()
        dp.callback_query.register = MagicMock()
        dp.message = MagicMock()
        dp.message.register = MagicMock()

        register_all(dp)

        registered_handlers = [c[0][0] for c in dp.callback_query.register.call_args_list]
        expected_handlers = [
            handle_support_callback, handle_editorial_callback,
            handle_duplicate_callback, handle_editor_source_callback,
            handle_linked_menu_callback, handle_code_rate_callback,
        ]
        assert registered_handlers == expected_handlers
