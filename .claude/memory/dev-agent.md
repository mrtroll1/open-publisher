# Dev Agent Memory

> This file accumulates context across autonomous sessions. The orchestrator updates it after each session.

## Session log

### Session 1 (plan-13, Phase 1 + 6.1)
- Implemented word-order-independent fuzzy matching in `contractor_repo.py`
- Lowered self-registration suggestion threshold from 0.8 to 0.6 in `contractor.py`
- Created `tests/test_fuzzy_matching.py` with 6 tests — all pass
- All 181 tests pass, ruff clean
- Linter noted moderate debt: `find_contractor` hardcodes 0.8 redundantly; `_word_independent_score` tested as private

### Session 2 (plan-13, Phase 2)
- Implemented StubContractor model (models.py): STUB enum, is_stub property, StubContractor class
- Added stub sheet support (contractor_repo.py): _parse_stub, save_stub, delete_contractor_from_sheet, load_all_contractors loads stubs
- Added create_stub to ContractorFactory (create.py)
- Implemented stub claiming flow (interact/contractor.py): _bind_contractor routes stubs to type selection, _complete_registration handles claiming_stub_id
- Supervisor: moved inline import to top-level, fixed ruff RUF005 lint
- Linter: extracted _upgrade_stub logic into ContractorFactory.upgrade_from_stub() public method for proper encapsulation
- All 181 tests pass, ruff clean
- 7 moderate debt items logged to memory/linter-debt.md

## Known issues

_None._

## Pitfalls

- GoalRepo uses `_row_to_dict` helper (SELECT * → dict via cursor.description) — different from PermissionRepo's positional tuple unpacking
- `update_goal`/`update_task` use sentinel string `"NOW()"` to inject SQL NOW() — fragile if someone passes literal "NOW()" as data
- FakeDb goal methods replicate SQL behavior in Python — may drift if repo changes
