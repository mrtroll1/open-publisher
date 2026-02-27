"""Flow engine: reads BotFlows declarations and registers aiogram handlers."""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Dispatcher, F, Router, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from telegram_bot.bot_helpers import is_admin
from telegram_bot.flow_dsl import (
    AdminCommand, BotFlows, Flow, FlowState, InputType, Transition,
)

logger = logging.getLogger(__name__)


def _build_states_group(flow: Flow) -> type[StatesGroup]:
    """Dynamically create a StatesGroup class from a Flow's state list."""
    attrs = {fs.name: State() for fs in flow.states}
    return type(
        f"{flow.name.title().replace('_', '')}States",
        (StatesGroup,),
        attrs,
    )


def _resolve_transition(flow_state: FlowState, key: Optional[str]) -> Optional[Transition]:
    """Find the matching transition for a handler's return key."""
    if key is None:
        return None
    transitions = flow_state.transitions
    return transitions.get(key) or transitions.get("default")


async def _apply_transition(
    message: types.Message,
    state: FSMContext,
    flow: Flow,
    current_fs: FlowState,
    key: str,
    states_cls: type,
) -> None:
    """Execute a transition: send message, run action, move to next state."""
    transition = _resolve_transition(current_fs, key)
    if not transition:
        return

    if transition.message:
        await message.answer(transition.message)

    if transition.action:
        await transition.action(message, state)

    if transition.to == "end":
        await state.clear()
    elif transition.to == "self":
        pass  # stay in current state
    else:
        target_state = getattr(states_cls, transition.to, None)
        if target_state:
            await state.set_state(target_state)
            target_fs = flow.state_by_name(transition.to)
            if target_fs:
                if target_fs.on_enter:
                    result = await target_fs.on_enter(message, state)
                    if result:
                        await _apply_transition(
                            message, state, flow, target_fs, result, states_cls,
                        )
                        return
                if target_fs.message:
                    msg = target_fs.message
                    if callable(msg):
                        msg = await msg(message, state)
                    if msg:
                        await message.answer(msg)


def _register_admin_command(router: Router, ac: AdminCommand) -> None:
    """Register a single admin command handler."""
    handler = ac.handler

    async def _handler(message: types.Message, state: FSMContext, _h=handler):
        if not is_admin(message.from_user.id):
            return
        await _h(message, state)

    _handler.__name__ = f"cmd_{ac.command}"
    router.message.register(_handler, Command(ac.command))


def _register_flow_command(
    router: Router, flow: Flow, states_cls: type, cmd_name: str,
) -> None:
    """Register the /command that triggers a flow's initial state."""
    initial_state_name = flow.initial_state or flow.states[0].name
    initial_state = getattr(states_cls, initial_state_name)
    initial_fs = flow.state_by_name(initial_state_name)

    async def _trigger(
        message: types.Message, state: FSMContext,
        _s=initial_state, _fs=initial_fs, _flow=flow, _sc=states_cls,
    ):
        if _flow.admin_only and not is_admin(message.from_user.id):
            return
        await state.set_state(_s)
        if _fs and _fs.on_enter:
            result = await _fs.on_enter(message, state)
            if result:
                await _apply_transition(message, state, _flow, _fs, result, _sc)
                return
        if _fs and _fs.message:
            msg = _fs.message
            if callable(msg):
                msg = await msg(message, state)
            if msg:
                await message.answer(msg)

    _trigger.__name__ = f"trigger_{flow.name}"
    router.message.register(_trigger, Command(cmd_name))


def _register_state_handler(
    router: Router, flow: Flow, fs: FlowState, state_obj: State, states_cls: type,
) -> None:
    """Register the input handler for a specific FSM state."""
    if not fs.handler:
        return

    if fs.input_type == InputType.DOCUMENT:
        filter_ = F.document
    else:
        filter_ = F.text & ~F.text.startswith("/")

    async def _state_handler(
        message: types.Message, state: FSMContext,
        _fs=fs, _flow=flow, _sc=states_cls,
    ):
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        result = await _fs.handler(message, state)
        if result is not None:
            await _apply_transition(message, state, _flow, _fs, result, _sc)

    _state_handler.__name__ = f"handle_{flow.name}_{fs.name}"
    router.message.register(_state_handler, state_obj, filter_)


def _register_catch_all(
    router: Router, flow: Flow, states_cls: type,
) -> None:
    """Register the catch-all text handler (fires only when no FSM state is active)."""
    initial_fs = flow.states[0] if flow.states else None
    handler_fn = initial_fs.handler if initial_fs else None

    async def _catch_all(
        message: types.Message, state: FSMContext,
        _h=handler_fn, _fs=initial_fs, _flow=flow, _sc=states_cls,
    ):
        current = await state.get_state()
        if current is not None:
            return  # another flow's state is active — skip
        if _h:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            result = await _h(message, state)
            if result is not None:
                await _apply_transition(message, state, _flow, _fs, result, _sc)

    _catch_all.__name__ = f"catch_all_{flow.name}"
    router.message.register(_catch_all, F.text & ~F.text.startswith("/"))


def _register_document_handler(router: Router, flow: Flow) -> None:
    """Register a document message handler."""
    fs = flow.states[0] if flow.states else None

    async def _doc_handler(
        message: types.Message, state: FSMContext,
        _fs=fs,
    ):
        if _fs and _fs.handler:
            await _fs.handler(message, state)

    _doc_handler.__name__ = f"doc_{flow.name}"
    router.message.register(_doc_handler, F.document)


# ── Public API ───────────────────────────────────────────────────────

def register_flows(dp: Dispatcher, bot_flows: BotFlows) -> None:
    """Register all flows and commands from a BotFlows declaration."""

    # /start
    if bot_flows.start_handler:
        handler = bot_flows.start_handler

        async def cmd_start(message: types.Message, state: FSMContext, _h=handler):
            await _h(message, state)

        dp.message.register(cmd_start, CommandStart())

    # Admin commands (stateless, highest priority after /start)
    admin_router = Router(name="admin")

    # Admin reply forwarding (must be before other text handlers)
    if bot_flows.reply_handler:
        reply_fn = bot_flows.reply_handler

        async def _reply_handler(message: types.Message, state: FSMContext, _h=reply_fn):
            if not is_admin(message.from_user.id):
                return
            await _h(message, state)

        admin_router.message.register(_reply_handler, F.reply_to_message, F.text)

    for ac in bot_flows.admin_commands:
        _register_admin_command(admin_router, ac)
    dp.include_router(admin_router)

    # Stateful flows — separate catch-all and document flows for last
    catch_all_flow = None
    document_flow = None

    for flow in bot_flows.flows:
        if flow.trigger == "text":
            catch_all_flow = flow
            continue
        if flow.trigger == "document":
            document_flow = flow
            continue

        # Command-triggered flow (e.g. /register)
        states_cls = _build_states_group(flow)
        flow_router = Router(name=flow.name)

        if flow.trigger and flow.trigger.startswith("/"):
            cmd_name = flow.trigger.lstrip("/")
            _register_flow_command(flow_router, flow, states_cls, cmd_name)

        for fs in flow.states:
            state_obj = getattr(states_cls, fs.name)
            _register_state_handler(flow_router, flow, fs, state_obj, states_cls)

        dp.include_router(flow_router)

    # Document handler
    if document_flow:
        doc_router = Router(name="document")
        _register_document_handler(doc_router, document_flow)
        dp.include_router(doc_router)

    # Catch-all text flow — LAST (lowest priority)
    if catch_all_flow:
        catch_router = Router(name="catch_all")
        states_cls = _build_states_group(catch_all_flow)

        for fs in catch_all_flow.states:
            state_obj = getattr(states_cls, fs.name)
            _register_state_handler(catch_router, catch_all_flow, fs, state_obj, states_cls)

        _register_catch_all(catch_router, catch_all_flow, states_cls)
        dp.include_router(catch_router)
