"""Tests for telegram_bot/flow_engine.py — pure helper functions."""

import pytest

from aiogram.fsm.state import StatesGroup, State

from telegram_bot.flow_engine import _build_states_group, _resolve_transition
from telegram_bot.flow_dsl import Flow, FlowState, Transition


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
