"""Tests for telegram_bot/flow_engine.py — pure helper functions."""

import pytest
from unittest.mock import MagicMock, patch

from aiogram import Dispatcher
from aiogram.fsm.state import StatesGroup, State

from telegram_bot.flow_engine import _build_states_group, _resolve_transition, register_flows
from telegram_bot.flow_dsl import BotFlows, Flow, FlowState, GroupChatConfig, Transition


# ===================================================================
#  _build_states_group()
# ===================================================================

class TestBuildStatesGroup:

    def test_creates_states_group(self):
        flow = Flow(
            name="test",
            states=[
                FlowState(name="alpha"),
                FlowState(name="beta"),
            ],
        )
        cls = _build_states_group(flow)
        assert issubclass(cls, StatesGroup)

    def test_states_are_attributes(self):
        flow = Flow(
            name="test",
            states=[
                FlowState(name="waiting_input"),
                FlowState(name="confirm"),
            ],
        )
        cls = _build_states_group(flow)
        assert hasattr(cls, "waiting_input")
        assert hasattr(cls, "confirm")

    def test_attributes_are_state_instances(self):
        flow = Flow(
            name="test",
            states=[FlowState(name="step1")],
        )
        cls = _build_states_group(flow)
        assert isinstance(cls.step1, State)

    def test_class_name_from_flow_name(self):
        flow = Flow(name="contractor", states=[FlowState(name="s")])
        cls = _build_states_group(flow)
        assert "Contractor" in cls.__name__

    def test_underscore_flow_name(self):
        flow = Flow(name="my_flow", states=[FlowState(name="s")])
        cls = _build_states_group(flow)
        assert "My" in cls.__name__
        assert "Flow" in cls.__name__

    def test_empty_states(self):
        flow = Flow(name="empty", states=[])
        cls = _build_states_group(flow)
        assert issubclass(cls, StatesGroup)

    def test_single_state(self):
        flow = Flow(name="single", states=[FlowState(name="only")])
        cls = _build_states_group(flow)
        assert hasattr(cls, "only")


# ===================================================================
#  _resolve_transition()
# ===================================================================

class TestResolveTransition:

    def test_returns_none_for_none_key(self):
        fs = FlowState(name="test", transitions={"go": Transition(to="next")})
        assert _resolve_transition(fs, None) is None

    def test_finds_exact_key(self):
        t = Transition(to="next_state")
        fs = FlowState(name="test", transitions={"go": t})
        result = _resolve_transition(fs, "go")
        assert result is t

    def test_returns_none_for_missing_key(self):
        fs = FlowState(name="test", transitions={"go": Transition(to="next")})
        assert _resolve_transition(fs, "missing") is None

    def test_falls_back_to_default(self):
        t_default = Transition(to="fallback")
        fs = FlowState(name="test", transitions={"default": t_default})
        result = _resolve_transition(fs, "unknown_key")
        assert result is t_default

    def test_exact_key_preferred_over_default(self):
        t_exact = Transition(to="exact")
        t_default = Transition(to="fallback")
        fs = FlowState(
            name="test",
            transitions={"go": t_exact, "default": t_default},
        )
        result = _resolve_transition(fs, "go")
        assert result is t_exact

    def test_empty_transitions(self):
        fs = FlowState(name="test", transitions={})
        assert _resolve_transition(fs, "any") is None


# ===================================================================
#  register_flows() — group config wiring
# ===================================================================

class TestRegisterFlowsGroupConfig:

    def test_group_router_included_when_configs_present(self):
        dp = Dispatcher()
        gc = GroupChatConfig(chat_id=-100111, allowed_commands=["health"])
        bf = BotFlows(group_configs=[gc])

        initial_router_count = len(dp.sub_routers)
        register_flows(dp, bf)
        assert len(dp.sub_routers) > initial_router_count

    def test_no_group_router_when_configs_empty(self):
        dp = Dispatcher()
        bf = BotFlows(group_configs=[])

        register_flows(dp, bf)
        router_names = [r.name for r in dp.sub_routers]
        assert "group" not in router_names

    def test_group_router_named_group(self):
        dp = Dispatcher()
        gc = GroupChatConfig(chat_id=-100111, allowed_commands=["health"])
        bf = BotFlows(group_configs=[gc])

        register_flows(dp, bf)
        router_names = [r.name for r in dp.sub_routers]
        assert "group" in router_names
