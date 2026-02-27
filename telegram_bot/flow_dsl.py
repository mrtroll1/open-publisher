"""Declarative flow DSL — dataclasses that describe bot conversation flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional, Union

from aiogram import types
from aiogram.fsm.context import FSMContext

# Handler: receives (message, state), returns optional transition key.
# Returning None = stay in current state. Returning a string picks a transition.
HandlerFn = Callable[[types.Message, FSMContext], Awaitable[Optional[str]]]

# Action: receives (message, state), returns nothing. Side-effects only.
ActionFn = Callable[[types.Message, FSMContext], Awaitable[None]]


class InputType(Enum):
    TEXT = "text"
    DOCUMENT = "document"


@dataclass
class Transition:
    """A possible transition out of a state.

    to:      Target state name, "end" to clear FSM, or "self" to loop.
    message: Optional text to send when this transition fires.
    action:  Optional callback to run when this transition fires.
    """
    to: str = "end"
    message: Optional[str] = None
    action: Optional[ActionFn] = None


@dataclass
class FlowState:
    """A single state in a conversation flow.

    name:        State identifier (becomes the aiogram State name).
    message:     Text sent when entering this state. Can be a string or an
                 async callable(message, state) -> str for dynamic prompts.
    on_enter:    Optional callback run on state entry. If it returns a string,
                 that string is used as transition key (short-circuit).
    handler:     Callback that processes user input. Returns a transition key
                 or None to stay in the current state.
    input_type:  What kind of message triggers the handler.
    transitions: Map from handler return value -> Transition.
    """
    name: str
    message: Optional[Union[str, Callable]] = None
    on_enter: Optional[HandlerFn] = None
    handler: Optional[HandlerFn] = None
    input_type: InputType = InputType.TEXT
    transitions: dict[str, Transition] = field(default_factory=dict)


@dataclass
class Flow:
    """A complete conversation flow (maps to one StatesGroup).

    name:          Flow identifier.
    description:   Human-readable description.
    trigger:       How this flow starts: "/command", "text" (catch-all), or "document".
    admin_only:    If True, only admin users can trigger this flow.
    initial_state: Name of the first state to enter.
    states:        Ordered list of FlowStates.
    """
    name: str
    description: str = ""
    trigger: Optional[str] = None
    admin_only: bool = False
    initial_state: Optional[str] = None
    states: list[FlowState] = field(default_factory=list)

    def state_by_name(self, name: str) -> Optional[FlowState]:
        for s in self.states:
            if s.name == name:
                return s
        return None


@dataclass
class AdminCommand:
    """A stateless admin command — no FSM, just command -> handler.

    command:     Slash command without the slash (e.g. "generate").
    description: Human-readable description.
    handler:     Async callback (message, state) -> None.
    usage:       Usage hint (e.g. "/generate <name>").
    """
    command: str
    description: str = ""
    handler: Optional[HandlerFn] = None
    usage: str = ""


@dataclass
class BotFlows:
    """Top-level container: everything the engine needs to wire up the bot."""
    flows: list[Flow] = field(default_factory=list)
    admin_commands: list[AdminCommand] = field(default_factory=list)
    start_handler: Optional[HandlerFn] = None
    reply_handler: Optional[HandlerFn] = None
