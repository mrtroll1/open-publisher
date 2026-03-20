"""Tests for GoalMonitor checkpoint detection."""

from backend.commands.goal_monitor import GoalMonitor


def test_checkpoint_created_when_agent_done_and_next_is_user(fake_db, fake_gemini):
    goal = fake_db.create_goal(title="Pipeline")
    t1 = fake_db.create_task(title="Research", goal_id=goal["id"], assigned_to="agent")
    t2 = fake_db.create_task(title="Approve", goal_id=goal["id"], assigned_to="user", depends_on=t1["id"])

    # Mark t1 as done (simulating agent completion)
    fake_db.update_task(t1["id"], status="done", result="Found 10 outlets")

    monitor = GoalMonitor(fake_db, fake_gemini)
    result = monitor.run()

    assert result["checkpoints"] == 1
    # t2 should be in_progress now
    assert fake_db.get_task(t2["id"])["status"] == "in_progress"
    # Notification created
    pending = fake_db.get_pending_notifications()
    checkpoint_notifs = [n for n in pending if n["type"] == "checkpoint_ready"]
    assert len(checkpoint_notifs) == 1
    assert checkpoint_notifs[0]["payload"]["task_id"] == str(t2["id"])


def test_agent_to_agent_chain_activates_next(fake_db, fake_gemini):
    """When an agent task completes and next is also agent, it should be activated."""
    goal = fake_db.create_goal(title="Pipeline")
    t1 = fake_db.create_task(title="Step 1", goal_id=goal["id"], assigned_to="agent")
    t2 = fake_db.create_task(title="Step 2", goal_id=goal["id"], assigned_to="agent", depends_on=t1["id"])
    fake_db.update_task(t1["id"], status="done", result="Done")

    monitor = GoalMonitor(fake_db, fake_gemini)
    monitor.run()

    # t2 should be activated (in_progress), no checkpoint notification
    assert fake_db.get_task(t2["id"])["status"] == "in_progress"
    checkpoint_notifs = [n for n in fake_db.get_pending_notifications() if n["type"] == "checkpoint_ready"]
    assert len(checkpoint_notifs) == 0
