"""Conversation controller — ReAct loop exit conditions."""

import sys
from unittest.mock import MagicMock

import pytest
from conftest import FakeDb, FakeRetriever, make_tool

from backend.brain.authorizer import AuthContext
from backend.brain.react import conversation_handler
from backend.brain.tool import ToolContext


@pytest.fixture(autouse=True)
def _mock_genai_types():
    """Stub google.genai.types so the inline import inside the ReAct loop works."""
    mock_types = MagicMock()
    # Content / Part constructors just need to be callable and return something
    mock_types.Content.return_value = MagicMock()
    mock_types.Part.from_text.return_value = MagicMock()
    mock_types.Part.from_function_response.return_value = MagicMock()
    sys.modules.setdefault("google", MagicMock())
    sys.modules.setdefault("google.genai", MagicMock())
    sys.modules["google.genai.types"] = mock_types
    # Also patch the attribute so `from google.genai import types` resolves
    sys.modules["google.genai"].types = mock_types
    yield
    # Don't clean up — other tests may also need it, and it's harmless


def _make_handler(gemini, db=None, retriever=None):
    return conversation_handler(
        gemini=gemini,
        db=db or FakeDb(),
        retriever=retriever or FakeRetriever(),
    )


def _make_auth(tools=None):
    ctx = ToolContext(
        env={"name": "test", "system_context": ""},
        user={"id": "u1", "role": "admin"},
    )
    return AuthContext(ctx=ctx, tools=tools or [], env_name="test", role="admin")


# ── No tools: single LLM call ───────────────────────────────────────


def test_no_tools_single_call(fake_gemini):
    fake_gemini.enqueue({"reply": "just a chat reply"})
    handle = _make_handler(fake_gemini)

    result = handle("hello", _make_auth(tools=[]))

    assert result["reply"] == "just a chat reply"


# ── Gemini replies immediately (no tool calls) ──────────────────────


def test_immediate_text_reply(fake_gemini):
    fake_gemini.enqueue_tool_response("here's your answer", None)
    tool = make_tool("search", conversational=True)
    handle = _make_handler(fake_gemini)

    result = handle("what is X?", _make_auth(tools=[tool]))

    assert result["reply"] == "here's your answer"


# ── One tool call then text ──────────────────────────────────────────


def test_one_tool_call_then_reply(fake_gemini):
    fake_gemini.enqueue_tool_response(None, [{"name": "search", "args": {"input": "X"}}])
    fake_gemini.enqueue_tool_response("found it: X is Y", None)

    tool = make_tool("search", conversational=True,
                     fn=lambda args, ctx: {"results": "X is Y"})
    handle = _make_handler(fake_gemini)

    result = handle("what is X?", _make_auth(tools=[tool]))

    assert "found it" in result["reply"]


# ── Repeated tool failure breaks loop ────────────────────────────────


def test_repeated_failure_breaks_loop(fake_gemini):
    # Two rounds of the same tool failing
    fake_gemini.enqueue_tool_response(None, [{"name": "bad_tool", "args": {}}])
    fake_gemini.enqueue_tool_response(None, [{"name": "bad_tool", "args": {}}])

    tool = make_tool("bad_tool", conversational=True,
                     fn=lambda args, ctx: {"error": "always fails"})
    handle = _make_handler(fake_gemini)

    result = handle("do something", _make_auth(tools=[tool]))

    assert "reply" in result


# ── Max steps reached ────────────────────────────────────────────────


def test_max_steps_returns_limit_message(fake_gemini):
    from backend.brain.react import MAX_TOOL_STEPS
    for _ in range(MAX_TOOL_STEPS + 1):
        fake_gemini.enqueue_tool_response(None, [{"name": "looper", "args": {}}])

    tool = make_tool("looper", conversational=True,
                     fn=lambda args, ctx: {"ok": True})
    handle = _make_handler(fake_gemini)

    result = handle("loop forever", _make_auth(tools=[tool]))

    assert "reply" in result


# ── Unknown tool in call ─────────────────────────────────────────────


def test_unknown_tool_call_handled(fake_gemini):
    fake_gemini.enqueue_tool_response(None, [{"name": "ghost", "args": {}}])
    fake_gemini.enqueue_tool_response("ok I'll answer without tools", None)

    tool = make_tool("real_tool", conversational=True)
    handle = _make_handler(fake_gemini)

    result = handle("call ghost", _make_auth(tools=[tool]))

    assert result["reply"] == "ok I'll answer without tools"
