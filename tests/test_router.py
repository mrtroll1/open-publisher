"""Router — does it classify NL to the right tool (or conversation)?"""

from conftest import FakeGemini, make_tool

from backend.brain.router import Router


def _make_router(gemini_response: dict):
    gemini = FakeGemini()
    gemini.enqueue(gemini_response)
    return Router(gemini)


# ── Classification ──────────────────────────────────────────────────


def test_routes_to_matching_tool():
    tool = make_tool("health")
    router = _make_router({"command": "health"})

    result = router.route("run health check", [tool])

    assert result is tool


def test_conversation_keyword_returns_none():
    tool = make_tool("health")
    router = _make_router({"command": "conversation"})

    result = router.route("how are you?", [tool])

    assert result is None


def test_unknown_tool_name_returns_none():
    tool = make_tool("health")
    router = _make_router({"command": "nonexistent"})

    result = router.route("do something weird", [tool])

    assert result is None


# ── Filtering ────────────────────────────────────────────────────────


def test_non_routable_tools_filtered_out():
    routable = make_tool("health", nl_routable=True)
    non_routable = make_tool("invoice", nl_routable=False)
    router = _make_router({"command": "invoice"})

    result = router.route("generate invoice", [routable, non_routable])

    # Even though Gemini said "invoice", it was filtered out
    assert result is None


def test_empty_tools_returns_none_without_calling_gemini():
    gemini = FakeGemini()
    # Don't enqueue anything — if Gemini is called, it'll return a default
    router = Router(gemini)

    result = router.route("hello", [])

    assert result is None


def test_all_non_routable_returns_none():
    non_routable = make_tool("db", nl_routable=False)
    gemini = FakeGemini()
    router = Router(gemini)

    result = router.route("query the database", [non_routable])

    assert result is None
