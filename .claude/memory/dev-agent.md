# Dev Agent Memory

> This file accumulates context across autonomous sessions. The orchestrator updates it after each session.

## Known issues

_None._

## Pitfalls

- GoalRepo uses `_row_to_dict` helper (SELECT * → dict via cursor.description) — different from PermissionRepo's positional tuple unpacking
- `update_goal`/`update_task` use sentinel string `"NOW()"` to inject SQL NOW() — fragile if someone passes literal "NOW()" as data
- FakeDb goal methods replicate SQL behavior in Python — may drift if repo changes
