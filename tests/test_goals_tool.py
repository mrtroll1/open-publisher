"""Tests for the goals tool (make_goals_tool)."""

from backend.brain.tool import ToolContext
from backend.brain.tools.goals import make_goals_tool


def _ctx():
    return ToolContext(env={"name": "main"}, user={"id": "u1", "role": "admin"})


def test_list_empty(fake_db, fake_gemini):
    tool = make_goals_tool(fake_db, fake_gemini)
    result = tool.fn({"action": "list"}, _ctx())
    assert result == {"goals": []}


def test_create_and_list(fake_db, fake_gemini):
    tool = make_goals_tool(fake_db, fake_gemini)
    created = tool.fn({"action": "create", "title": "New goal", "priority": 2}, _ctx())
    assert "goal" in created
    assert created["goal"]["title"] == "New goal"

    listed = tool.fn({"action": "list"}, _ctx())
    assert len(listed["goals"]) == 1
    assert listed["goals"][0]["id"] == created["goal"]["id"]


def test_create_missing_title(fake_db, fake_gemini):
    tool = make_goals_tool(fake_db, fake_gemini)
    result = tool.fn({"action": "create"}, _ctx())
    assert "error" in result


def test_update_goal(fake_db, fake_gemini):
    tool = make_goals_tool(fake_db, fake_gemini)
    created = tool.fn({"action": "create", "title": "G1"}, _ctx())
    goal_id = created["goal"]["id"]

    updated = tool.fn({"action": "update", "goal_id": goal_id, "status": "paused"}, _ctx())
    assert updated["updated"]["status"] == "paused"


def test_progress_action(fake_db, fake_gemini):
    tool = make_goals_tool(fake_db, fake_gemini)
    created = tool.fn({"action": "create", "title": "G1"}, _ctx())
    goal_id = created["goal"]["id"]

    tool.fn({"action": "progress", "goal_id": goal_id, "note": "Step done"}, _ctx())

    status = tool.fn({"action": "status", "goal_id": goal_id}, _ctx())
    assert len(status["recent_progress"]) == 1
    assert status["recent_progress"][0]["note"] == "Step done"


def test_plan_action(fake_db, fake_gemini):
    tool = make_goals_tool(fake_db, fake_gemini)
    created = tool.fn({"action": "create", "title": "Big goal"}, _ctx())
    goal_id = created["goal"]["id"]

    fake_gemini.enqueue({"tasks": [{"title": "T1", "assigned_to": "user"}]})

    result = tool.fn({"action": "plan", "goal_id": goal_id}, _ctx())
    assert len(result["tasks_created"]) == 1
    assert result["tasks_created"][0]["title"] == "T1"
    assert result["tasks_created"][0]["goal_id"] == goal_id

    tasks = fake_db.list_tasks(goal_id=goal_id)
    assert len(tasks) == 1
