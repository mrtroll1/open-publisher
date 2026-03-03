"""Tests for telegram_bot/flow_dsl.py — pure data structure logic."""

import pytest

from telegram_bot.flow_dsl import (
    AdminCommand,
    BotFlows,
    Flow,
    FlowState,
    GroupChatConfig,
    InputType,
    Transition,
)


# ===================================================================
#  FlowState defaults
# ===================================================================

class TestFlowStateDefaults:

    def test_default_input_type_is_text(self):
        fs = FlowState(name="test")
        assert fs.input_type == InputType.TEXT

    def test_default_transitions_empty(self):
        fs = FlowState(name="test")
        assert fs.transitions == {}

    def test_default_handler_none(self):
        fs = FlowState(name="test")
        assert fs.handler is None

    def test_default_message_none(self):
        fs = FlowState(name="test")
        assert fs.message is None

    def test_default_on_enter_none(self):
        fs = FlowState(name="test")
        assert fs.on_enter is None


# ===================================================================
#  Transition defaults
# ===================================================================

class TestTransitionDefaults:

    def test_default_to_is_end(self):
        t = Transition()
        assert t.to == "end"

    def test_default_message_none(self):
        t = Transition()
        assert t.message is None

    def test_default_action_none(self):
        t = Transition()
        assert t.action is None

    def test_custom_to(self):
        t = Transition(to="next_state")
        assert t.to == "next_state"


# ===================================================================
#  Flow.state_by_name()
# ===================================================================

class TestFlowStateByName:

    def test_finds_existing_state(self):
        flow = Flow(
            name="test",
            states=[
                FlowState(name="alpha"),
                FlowState(name="beta"),
                FlowState(name="gamma"),
            ],
        )
        result = flow.state_by_name("beta")
        assert result is not None
        assert result.name == "beta"

    def test_returns_none_for_missing(self):
        flow = Flow(name="test", states=[FlowState(name="alpha")])
        assert flow.state_by_name("nonexistent") is None

    def test_empty_states(self):
        flow = Flow(name="test", states=[])
        assert flow.state_by_name("anything") is None

    def test_returns_first_if_duplicates(self):
        s1 = FlowState(name="dup", message="first")
        s2 = FlowState(name="dup", message="second")
        flow = Flow(name="test", states=[s1, s2])
        result = flow.state_by_name("dup")
        assert result.message == "first"


# ===================================================================
#  Flow defaults
# ===================================================================

class TestFlowDefaults:

    def test_default_admin_only_false(self):
        flow = Flow(name="test")
        assert flow.admin_only is False

    def test_default_trigger_none(self):
        flow = Flow(name="test")
        assert flow.trigger is None

    def test_default_states_empty(self):
        flow = Flow(name="test")
        assert flow.states == []

    def test_default_initial_state_none(self):
        flow = Flow(name="test")
        assert flow.initial_state is None


# ===================================================================
#  AdminCommand defaults
# ===================================================================

class TestAdminCommandDefaults:

    def test_default_handler_none(self):
        ac = AdminCommand(command="test")
        assert ac.handler is None

    def test_default_usage_empty(self):
        ac = AdminCommand(command="test")
        assert ac.usage == ""

    def test_default_description_empty(self):
        ac = AdminCommand(command="test")
        assert ac.description == ""


# ===================================================================
#  BotFlows defaults
# ===================================================================

class TestBotFlowsDefaults:

    def test_default_flows_empty(self):
        bf = BotFlows()
        assert bf.flows == []

    def test_default_admin_commands_empty(self):
        bf = BotFlows()
        assert bf.admin_commands == []

    def test_default_start_handler_none(self):
        bf = BotFlows()
        assert bf.start_handler is None

    def test_default_reply_handler_none(self):
        bf = BotFlows()
        assert bf.reply_handler is None


# ===================================================================
#  InputType enum
# ===================================================================

class TestInputType:

    def test_text_value(self):
        assert InputType.TEXT.value == "text"

    def test_document_value(self):
        assert InputType.DOCUMENT.value == "document"


# ===================================================================
#  GroupChatConfig
# ===================================================================

class TestGroupChatConfig:

    def test_defaults(self):
        gc = GroupChatConfig(chat_id=-1001234567890)
        assert gc.chat_id == -1001234567890
        assert gc.allowed_commands == []
        assert gc.natural_language is True

    def test_custom_allowed_commands(self):
        gc = GroupChatConfig(
            chat_id=-100111,
            allowed_commands=["health", "code"],
        )
        assert gc.allowed_commands == ["health", "code"]

    def test_natural_language_disabled(self):
        gc = GroupChatConfig(
            chat_id=-100222,
            natural_language=False,
        )
        assert gc.natural_language is False

    def test_filtering_configured_chat(self):
        configs = [
            GroupChatConfig(chat_id=-100111, allowed_commands=["health"]),
            GroupChatConfig(chat_id=-100222, allowed_commands=["code"]),
        ]
        config_by_chat = {gc.chat_id: gc for gc in configs}

        assert -100111 in config_by_chat
        assert config_by_chat[-100111].allowed_commands == ["health"]

    def test_filtering_unconfigured_chat(self):
        configs = [
            GroupChatConfig(chat_id=-100111, allowed_commands=["health"]),
        ]
        config_by_chat = {gc.chat_id: gc for gc in configs}

        assert -100999 not in config_by_chat
        assert config_by_chat.get(-100999) is None


# ===================================================================
#  BotFlows.group_configs
# ===================================================================

class TestBotFlowsGroupConfigs:

    def test_default_group_configs_empty(self):
        bf = BotFlows()
        assert bf.group_configs == []

    def test_group_configs_stored(self):
        gc = GroupChatConfig(chat_id=-100111, allowed_commands=["health"])
        bf = BotFlows(group_configs=[gc])
        assert len(bf.group_configs) == 1
        assert bf.group_configs[0].chat_id == -100111
