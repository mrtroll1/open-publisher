"""Tests for telegram_bot/flows.py — structural validation of flow definitions."""

import pytest

from telegram_bot.flows import (
    admin_commands,
    bot_flows,
    contractor_flow,
    document_flow,
)
from telegram_bot.flow_dsl import InputType


# ===================================================================
#  Contractor flow structure
# ===================================================================

class TestContractorFlowStructure:

    def test_name(self):
        assert contractor_flow.name == "contractor"

    def test_trigger_is_text(self):
        assert contractor_flow.trigger == "text"

    def test_has_states(self):
        assert len(contractor_flow.states) > 0

    def test_all_states_have_handlers(self):
        for s in contractor_flow.states:
            assert s.handler is not None, f"State '{s.name}' has no handler"

    def test_lookup_is_first_state(self):
        assert contractor_flow.states[0].name == "lookup"

    def test_state_names_unique(self):
        names = [s.name for s in contractor_flow.states]
        assert len(names) == len(set(names))

    def test_expected_states_present(self):
        names = {s.name for s in contractor_flow.states}
        expected = {
            "lookup", "waiting_verification", "waiting_type",
            "waiting_data", "waiting_amount",
            "waiting_update_data", "waiting_editor_source_name",
        }
        assert expected.issubset(names)

    def test_lookup_transitions(self):
        lookup = contractor_flow.state_by_name("lookup")
        assert "register" in lookup.transitions

    def test_waiting_verification_transitions(self):
        wv = contractor_flow.state_by_name("waiting_verification")
        assert "verified" in wv.transitions
        assert "invoice" in wv.transitions

    def test_waiting_type_has_message(self):
        wt = contractor_flow.state_by_name("waiting_type")
        assert wt.message is not None

    def test_waiting_type_transitions(self):
        wt = contractor_flow.state_by_name("waiting_type")
        assert "valid" in wt.transitions

    def test_register_transition_goes_to_waiting_type(self):
        lookup = contractor_flow.state_by_name("lookup")
        assert lookup.transitions["register"].to == "waiting_type"


# ===================================================================
#  Document flow structure
# ===================================================================

class TestDocumentFlowStructure:

    def test_name(self):
        assert document_flow.name == "document"

    def test_trigger_is_document(self):
        assert document_flow.trigger == "document"

    def test_has_one_state(self):
        assert len(document_flow.states) == 1

    def test_state_input_type_document(self):
        assert document_flow.states[0].input_type == InputType.DOCUMENT

    def test_state_has_handler(self):
        assert document_flow.states[0].handler is not None


# ===================================================================
#  Admin commands structure
# ===================================================================

class TestAdminCommandsStructure:

    def test_has_commands(self):
        assert len(admin_commands) > 0

    def test_all_commands_have_handlers(self):
        for ac in admin_commands:
            assert ac.handler is not None, f"Command '{ac.command}' has no handler"

    def test_all_commands_have_names(self):
        for ac in admin_commands:
            assert ac.command, "Admin command with empty name"

    def test_expected_commands_present(self):
        names = {ac.command for ac in admin_commands}
        assert "generate" in names
        assert "budget" in names
        assert "generate_invoices" in names

    def test_command_names_unique(self):
        names = [ac.command for ac in admin_commands]
        assert len(names) == len(set(names))


# ===================================================================
#  BotFlows assembly
# ===================================================================

class TestBotFlowsAssembly:

    def test_has_flows(self):
        assert len(bot_flows.flows) == 2

    def test_contractor_flow_included(self):
        names = [f.name for f in bot_flows.flows]
        assert "contractor" in names

    def test_document_flow_included(self):
        names = [f.name for f in bot_flows.flows]
        assert "document" in names

    def test_has_start_handler(self):
        assert bot_flows.start_handler is not None

    def test_has_reply_handler(self):
        assert bot_flows.reply_handler is not None

    def test_has_admin_commands(self):
        assert len(bot_flows.admin_commands) > 0

    def test_group_configs_is_list(self):
        assert isinstance(bot_flows.group_configs, list)
