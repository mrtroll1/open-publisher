"""Goal & task repository — goals, tasks, progress, notifications."""

from __future__ import annotations

import json

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


def _row_to_dict(cur, row):
    if row is None:
        return None
    return {col.name: val for col, val in zip(cur.description, row, strict=False)}


def _rows_to_dicts(cur):
    return [_row_to_dict(cur, row) for row in cur.fetchall()]


class GoalRepo(BasePostgresRepo):

    # ── Goals ──

    def create_goal(self, title: str, description: str | None = None, priority: int = 3, deadline=None) -> dict:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO goals (title, description, priority, deadline)
                   VALUES (%s, %s, %s, %s) RETURNING *""",
                (title, description, priority, deadline),
            )
            return _row_to_dict(cur, cur.fetchone())

    def update_goal(self, goal_id: str, **fields) -> dict:
        valid = {"title", "description", "status", "priority", "deadline"}
        unknown = set(fields) - valid
        if unknown:
            raise ValueError(f"Unknown fields: {unknown}")
        fields["updated_at"] = "NOW()"
        set_parts = []
        values = []
        for k, v in fields.items():
            if v == "NOW()":
                set_parts.append(f"{k} = NOW()")
            else:
                set_parts.append(f"{k} = %s")
                values.append(v)
        values.append(goal_id)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE goals SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values,
            )
            return _row_to_dict(cur, cur.fetchone())

    def list_goals(self, status: str | None = None) -> list[dict]:
        with self._cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM goals WHERE status = %s ORDER BY priority ASC, created_at DESC",
                    (status,),
                )
            else:
                cur.execute("SELECT * FROM goals ORDER BY priority ASC, created_at DESC")
            return _rows_to_dicts(cur)

    def get_goal(self, goal_id: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM goals WHERE id = %s", (goal_id,))
            return _row_to_dict(cur, cur.fetchone())

    # ── Tasks ──

    def create_task(  # noqa: PLR0913
        self, title: str, description: str | None = None, goal_id: str | None = None,
        trigger_condition: str | None = None, due_date=None, assigned_to: str = "user",
        depends_on: str | None = None,
    ) -> dict:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO tasks (title, description, goal_id, trigger_condition, due_date, assigned_to, depends_on)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (title, description, goal_id, trigger_condition, due_date, assigned_to, depends_on),
            )
            return _row_to_dict(cur, cur.fetchone())

    def update_task(self, task_id: str, **fields) -> dict:
        valid = {"title", "description", "status", "goal_id", "trigger_condition", "due_date", "assigned_to", "result", "depends_on"}
        unknown = set(fields) - valid
        if unknown:
            raise ValueError(f"Unknown fields: {unknown}")
        if fields.get("status") == "done":
            fields["completed_at"] = "NOW()"
        set_parts = []
        values = []
        for k, v in fields.items():
            if v == "NOW()":
                set_parts.append(f"{k} = NOW()")
            else:
                set_parts.append(f"{k} = %s")
                values.append(v)
        values.append(task_id)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE tasks SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values,
            )
            return _row_to_dict(cur, cur.fetchone())

    def list_tasks(self, goal_id: str | None = None, status: str | None = None, assigned_to: str | None = None) -> list[dict]:
        conditions = []
        values = []
        if goal_id is not None:
            conditions.append("goal_id = %s")
            values.append(goal_id)
        if status is not None:
            conditions.append("status = %s")
            values.append(status)
        if assigned_to is not None:
            conditions.append("assigned_to = %s")
            values.append(assigned_to)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM tasks{where} ORDER BY created_at", values)
            return _rows_to_dicts(cur)

    def get_task(self, task_id: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            return _row_to_dict(cur, cur.fetchone())

    def get_triggered_tasks(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM tasks WHERE status = 'pending' AND trigger_condition IS NOT NULL"
            )
            return _rows_to_dicts(cur)

    def get_due_tasks(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM tasks WHERE status = 'pending' AND due_date IS NOT NULL AND due_date < NOW()"
            )
            return _rows_to_dicts(cur)

    # ── Progress ──

    def add_progress(self, goal_id: str, note: str, source: str = "user") -> dict:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO goal_progress (goal_id, note, source)
                   VALUES (%s, %s, %s) RETURNING *""",
                (goal_id, note, source),
            )
            return _row_to_dict(cur, cur.fetchone())

    def get_progress(self, goal_id: str, limit: int = 10) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM goal_progress WHERE goal_id = %s ORDER BY created_at DESC LIMIT %s",
                (goal_id, limit),
            )
            return _rows_to_dicts(cur)

    # ── Summary ──

    def get_active_goals_summary(self) -> str:
        with self._cursor() as cur:
            cur.execute(
                """SELECT g.title, g.priority, g.deadline,
                          COUNT(t.id) FILTER (WHERE t.status = 'done') AS done,
                          COUNT(t.id) AS total
                   FROM goals g
                   LEFT JOIN tasks t ON t.goal_id = g.id
                   WHERE g.status = 'active'
                   GROUP BY g.id
                   ORDER BY g.priority ASC, g.created_at DESC"""
            )
            lines = []
            for title, priority, deadline, done, total in cur.fetchall():
                dl = deadline.strftime("%Y-%m-%d") if deadline else "нет"
                lines.append(f'Цель [P{priority}]: "{title}" (дедлайн: {dl}, задач: {done}/{total})')
            return "\n".join(lines)

    # ── Notifications ──

    def create_notification(self, type: str, payload: dict) -> dict:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO notifications (type, payload)
                   VALUES (%s, %s) RETURNING *""",
                (type, json.dumps(payload, ensure_ascii=False)),
            )
            return _row_to_dict(cur, cur.fetchone())

    def get_pending_notifications(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM notifications WHERE read = FALSE ORDER BY created_at"
            )
            return _rows_to_dicts(cur)

    def mark_notifications_read(self, ids: list[str]) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE notifications SET read = TRUE WHERE id = ANY(%s)",
                (ids,),
            )
