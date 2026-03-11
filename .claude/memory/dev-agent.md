# Dev Agent Memory

> This file accumulates context across autonomous sessions. The orchestrator updates it after each session.

## Session log

### Session 1 (plan-13, Phase 1 + 6.1)
- Implemented word-order-independent fuzzy matching in `contractor_repo.py`
- Lowered self-registration suggestion threshold from 0.8 to 0.6 in `contractor.py`
- Created `tests/test_fuzzy_matching.py` with 6 tests — all pass
- All 181 tests pass, ruff clean
- Linter noted moderate debt: `find_contractor` hardcodes 0.8 redundantly; `_word_independent_score` tested as private

## Known issues

_None._

## Pitfalls

- GoalRepo uses `_row_to_dict` helper (SELECT * → dict via cursor.description) — different from PermissionRepo's positional tuple unpacking
- `update_goal`/`update_task` use sentinel string `"NOW()"` to inject SQL NOW() — fragile if someone passes literal "NOW()" as data
- FakeDb goal methods replicate SQL behavior in Python — may drift if repo changes
