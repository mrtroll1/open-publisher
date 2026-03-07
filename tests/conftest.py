"""Shared fixtures — fakes for the natural boundaries of the system."""
# ruff: noqa: E402

from __future__ import annotations

import os

# Stub required env vars before any backend imports trigger config.py
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REQUIRED = {
    "CONFIG_DIR": os.path.join(_PROJECT_ROOT, "config"),
    "ADMIN_TELEGRAM_TAG": "@test_admin",
    "GOOGLE_SERVICE_ACCOUNT_FILE": "/dev/null",
    "CONTRACTORS_SHEET_ID": "fake",
    "REPUBLIC_SITE_URL": "https://test.example.com",
    "REDEFINE_SITE_URL": "https://test2.example.com",
}
for k, v in _REQUIRED.items():
    os.environ.setdefault(k, v)

from unittest.mock import MagicMock

import pytest

from backend.brain.tool import TOOLS, Tool

# ── Fake DB ──────────────────────────────────────────────────────────


class FakeDb:
    """Minimal stand-in for DbGateway — returns canned data."""

    def __init__(self):
        self.environments: dict[str, dict] = {}
        self.environments_by_chat: dict[int, dict] = {}
        self.users: dict[int, dict] = {}
        self.messages: list[dict] = []
        self.run_logs: list[dict] = []

    def get_environment(self, env_id: str) -> dict | None:
        return self.environments.get(env_id)

    def get_environment_by_chat_id(self, chat_id: int) -> dict | None:
        return self.environments_by_chat.get(chat_id)

    def get_or_create_by_telegram_id(self, telegram_id: int) -> dict:
        return self.users.get(telegram_id, {"id": str(telegram_id), "role": "user", "telegram_id": telegram_id})

    def get_by_telegram_message_id(self, chat_id, message_id):
        return None

    def get_reply_chain(self, msg_id, depth=20):
        return []

    def log_run_step(self, run_id, step, type, content):
        self.run_logs.append({"run_id": run_id, "step": step, "type": type, "content": content})


# ── Fake Gemini ──────────────────────────────────────────────────────


class FakeGemini:
    """Returns pre-programmed responses. Queue responses with .enqueue()."""

    def __init__(self):
        self._responses: list = []
        self._tool_responses: list = []

    def enqueue(self, response: dict):
        self._responses.append(response)

    def enqueue_tool_response(self, text: str | None, tool_calls: list | None):
        """Queue a response for call_with_tools / continue_with_tool_results."""
        self._tool_responses.append((text, tool_calls))

    def call(self, prompt: str, model: str = "") -> dict:
        if self._responses:
            return self._responses.pop(0)
        return {"reply": "default fake reply"}

    def call_with_tools(self, system_prompt, user_input, declarations, model=""):
        if self._tool_responses:
            text, tool_calls = self._tool_responses.pop(0)
            return text, tool_calls, MagicMock() if tool_calls else None
        return "default reply", None, None

    def continue_with_tool_results(self, history, results, declarations, model="", extra_instruction=None):
        if self._tool_responses:
            text, tool_calls = self._tool_responses.pop(0)
            return text, tool_calls, MagicMock() if tool_calls else None
        return "continued reply", None, None


# ── Fake Retriever ───────────────────────────────────────────────────


class FakeRetriever:
    def get_user_context(self, user_id: str) -> str:
        return ""

    def get_core(self) -> str:
        return ""

    def get_multi_domain_context(self, domains: list[str]) -> str:
        return ""

    def retrieve(self, query: str, domains=None) -> str:
        return ""


# ── Test Tools ───────────────────────────────────────────────────────


def make_tool(name: str, *, nl_routable=True, conversational=False,
              permissions=None, fn=None) -> Tool:
    return Tool(
        name=name,
        description=f"Test tool: {name}",
        parameters={"type": "object", "properties": {"input": {"type": "string"}}},
        fn=fn or (lambda args, ctx: {"result": f"{name} called", "input": args.get("input")}),
        permissions=permissions or {"*": {"admin", "user"}},
        nl_routable=nl_routable,
        conversational=conversational,
    )


@pytest.fixture(autouse=True)
def _clean_tool_registry():
    """Save and restore the global TOOLS registry around each test."""
    saved = dict(TOOLS)
    yield
    TOOLS.clear()
    TOOLS.update(saved)


@pytest.fixture
def fake_db():
    return FakeDb()


@pytest.fixture
def fake_gemini():
    return FakeGemini()


@pytest.fixture
def fake_retriever():
    return FakeRetriever()
