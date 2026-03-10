"""Tests for FakeDb goal/task/progress/notification methods."""

import time
from datetime import UTC, datetime, timedelta

import pytest


def test_create_goal(fake_db):
    goal = fake_db.create_goal(title="Launch v2", priority=2)
    assert goal["title"] == "Launch v2"
    assert goal["priority"] == 2
    assert goal["status"] == "active"
    assert goal["description"] is None
    assert goal["deadline"] is None
    assert "id" in goal
    assert "created_at" in goal
    assert "updated_at" in goal


def test_update_goal_status(fake_db):
    goal = fake_db.create_goal(title="G1")
    created = goal["updated_at"]
    time.sleep(0.01)
    updated = fake_db.update_goal(goal["id"], status="done")
    assert updated["status"] == "done"
    assert updated["updated_at"] > created


def test_update_goal_invalid_field(fake_db):
    goal = fake_db.create_goal(title="G1")
    with pytest.raises(ValueError, match="Unknown fields"):
        fake_db.update_goal(goal["id"], bogus="x")


def test_list_goals_filters(fake_db):
    fake_db.create_goal(title="A1")
    fake_db.create_goal(title="A2")
    g3 = fake_db.create_goal(title="D1")
    fake_db.update_goal(g3["id"], status="done")

    assert len(fake_db.list_goals(status="active")) == 2
    assert len(fake_db.list_goals()) == 3


def test_create_task_with_goal(fake_db):
    goal = fake_db.create_goal(title="G1")
    task = fake_db.create_task(title="T1", goal_id=goal["id"])
    assert task["goal_id"] == goal["id"]
    assert task["status"] == "pending"


def test_create_task_standalone(fake_db):
    task = fake_db.create_task(title="Solo")
    assert task["goal_id"] is None


def test_update_task_done_sets_completed_at(fake_db):
    task = fake_db.create_task(title="T1")
    assert task["completed_at"] is None
    updated = fake_db.update_task(task["id"], status="done")
    assert updated["completed_at"] is not None


def test_get_triggered_tasks(fake_db):
    fake_db.create_task(title="T1", trigger_condition="when email arrives")
    fake_db.create_task(title="T2")
    triggered = fake_db.get_triggered_tasks()
    assert len(triggered) == 1
    assert triggered[0]["title"] == "T1"


def test_get_due_tasks(fake_db):
    past = datetime.now(UTC) - timedelta(hours=1)
    future = datetime.now(UTC) + timedelta(hours=1)
    fake_db.create_task(title="Overdue", due_date=past)
    fake_db.create_task(title="Later", due_date=future)
    due = fake_db.get_due_tasks()
    assert len(due) == 1
    assert due[0]["title"] == "Overdue"


def test_active_goals_summary_format(fake_db):
    goal = fake_db.create_goal(title="Ship it", priority=3)
    t1 = fake_db.create_task(title="T1", goal_id=goal["id"])
    fake_db.create_task(title="T2", goal_id=goal["id"])
    fake_db.update_task(t1["id"], status="done")

    summary = fake_db.get_active_goals_summary()
    assert 'Цель [P3]: "Ship it"' in summary
    assert "задач: 1/2" in summary


def test_active_goals_summary_empty(fake_db):
    assert fake_db.get_active_goals_summary() == ""


def test_notifications_lifecycle(fake_db):
    n = fake_db.create_notification("reminder", {"text": "hello"})
    pending = fake_db.get_pending_notifications()
    assert len(pending) == 1
    fake_db.mark_notifications_read([n["id"]])
    assert len(fake_db.get_pending_notifications()) == 0


def test_progress(fake_db):
    goal = fake_db.create_goal(title="G1")
    fake_db.add_progress(goal["id"], "Did step 1", source="agent")
    entries = fake_db.get_progress(goal["id"])
    assert len(entries) == 1
    assert entries[0]["note"] == "Did step 1"
    assert entries[0]["source"] == "agent"
