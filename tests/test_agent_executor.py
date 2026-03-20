"""Tests for AgentTaskExecutor."""

from backend.brain.agent_executor import AgentTaskExecutor


def test_executor_builds_input_with_dependency():
    calls = []

    def mock_conv_fn(input_text, auth, **kwargs):
        calls.append(input_text)
        return {"reply": "Agent completed the research"}

    executor = AgentTaskExecutor(mock_conv_fn)
    task = {"id": "t1", "title": "Analyze results", "description": "Deep analysis"}
    result = executor.execute(task, "Goal: launch media", "Previous: found 10 outlets")

    assert result["completed"] is True
    assert "Agent completed the research" in result["result"]
    assert "Analyze results" in calls[0]
    assert "found 10 outlets" in calls[0]


def test_executor_handles_error():
    def failing_fn(input_text, auth, **kwargs):
        raise RuntimeError("LLM unavailable")

    executor = AgentTaskExecutor(failing_fn)
    task = {"id": "t1", "title": "Fail task"}
    result = executor.execute(task, "Goal context")

    assert result["completed"] is False
    assert "LLM unavailable" in result["result"]
