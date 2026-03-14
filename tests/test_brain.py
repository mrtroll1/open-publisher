"""Brain — does routing dispatch correctly?"""

from conftest import make_tool

from backend.brain import Brain
from backend.brain.authorizer import AuthContext
from backend.brain.tool import ToolContext, register_tool


def _make_auth(tools=None, role="admin"):
    ctx = ToolContext(env={"name": "main"}, user={"id": "u1", "role": role})
    return AuthContext(ctx=ctx, tools=tools or [], env_name="main", role=role)


def _make_brain(auth, router_returns=None, conversation_returns=None):
    class FakeAuthorizer:
        def authorize(self, env_id, user_id):
            return auth

    class FakeRouter:
        def route(self, input, tools, **kwargs):
            return router_returns

    def conversation_fn(input, auth, **kw):
        return conversation_returns or {"reply": "conversation"}
    return Brain(FakeAuthorizer(), FakeRouter(), conversation_fn)


# ── Routing decision ────────────────────────────────────────────────


def test_router_returns_tool_executes_it():
    tool = make_tool("greet", fn=lambda args, ctx: {"greeting": f"hello {args['input']}"})
    auth = _make_auth(tools=[tool])
    brain = _make_brain(auth, router_returns=tool)

    result = brain.process("hi", "env1", "user1")

    assert result == {"greeting": "hello hi"}


def test_router_returns_none_goes_to_conversation():
    auth = _make_auth()
    brain = _make_brain(auth, router_returns=None, conversation_returns={"reply": "thought about it"})

    result = brain.process("what is life", "env1", "user1")

    assert result == {"reply": "thought about it"}


# ── Slash commands ──────────────────────────────────────────────────


def test_process_command_bypasses_router():
    tool = make_tool("health", fn=lambda args, ctx: {"status": "ok"})
    register_tool(tool)
    auth = _make_auth(tools=[tool])

    # Router that would fail if called
    class FailRouter:
        def route(self, *a):
            raise AssertionError("Router should not be called for commands")

    class FakeAuthorizer:
        def authorize(self, env_id, user_id):
            return auth

    brain = Brain(FakeAuthorizer(), FailRouter())

    result = brain.process_command("health", "", "env1", "user1")

    assert result == {"status": "ok"}


def test_process_command_passes_args_as_input():
    received = {}

    def capture(args, ctx):
        received.update(args)
        return {"ok": True}

    tool = make_tool("teach", fn=capture)
    register_tool(tool)
    auth = _make_auth(tools=[tool])

    class FakeAuthorizer:
        def authorize(self, env_id, user_id):
            return auth

    brain = Brain(FakeAuthorizer(), None)

    brain.process_command("teach", "https://example.com/article", "env1", "user1")

    assert received["input"] == "https://example.com/article"
