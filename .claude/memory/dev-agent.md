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

### Session 3 (plan-13, Phase 3)
- Implemented `change_contractor_type` in `contractor_repo.py`: deletes from old sheet, creates in new with preserved identity fields, resets invoice_number
- Added `change_type` handler in `interact/contractor.py`: supports self-service (menu button) and admin-initiated (via `target_contractor_id` in fsm_data), rejects stubs
- Updated `_complete_registration` to handle `changing_type_id` branch alongside existing `claiming_stub_id`
- Added `_execute_type_change` helper with null guard
- Menu button "Сменить тип контрагента" + `menu_callback` case
- Registered `"change_type"` in `_HANDLERS` (`interact/__init__.py`)
- Supervisor: added null guard in `_execute_type_change` (returns None + log instead of crash)
- Linter: improved error handling pattern (return None + user-friendly message instead of ValueError)
- Linter logged 4 moderate debt items (#11-#15) including non-atomic type change and missing tests
- All 181 tests pass, ruff clean

### Session 4 (plan-13, Phase 4)
- Implemented contractor lookup in redirect source flow (`interact/contractor.py`)
- `_add_editor_source` now does fuzzy search before adding redirect rule
- New methods: `_suggest_source_contractors`, `_offer_stub_or_raw`, `_create_stub_and_link`, `_finalize_editor_source`
- Extended `esrc_callback` with `link:`, `stub`, `raw` cases reading from fsm_data
- Supervisor: fixed bug where `esrc:link:<id>` ignored contractor ID (used raw typed name instead of display_name); updated test
- Linter: fixed triple `load_all_contractors()` call in esrc_callback path (each hits Google Sheets API)
- Linter logged 4 moderate debt items (#16-#19)
- All 182 tests pass, ruff clean
- Phases 1-4, 5.1-5.4, and 6.1 complete. Next: Phase 5.5 (admin DM NL routing) or Phase 6 (remaining tests)

### Session 5 (plan-13, Phase 5.1-5.4)
- Created migration 008: `editor_dm` environment + `contractors` tool permissions for admin+editor
- Added `upsert_article_rate_rule` and `get_article_rate_rule` to `rules_repo.py`
- Created `src/backend/brain/tools/contractors.py` with 5 actions: lookup, create_stub, add_redirect, set_rate, get_rate
- Registered tool in `tools/__init__.py` and `wiring.py`
- Supervisor: removed unused `gemini` parameter from `make_contractors_tool()` (tool doesn't need Gemini directly)
- Linter: fixed `load_article_rate_rules` to use `_ARTICLE_RATE_RANGE` constant instead of hardcoded string
- Linter logged 6 moderate debt items (repeated `load_all_contractors()` calls in tool actions, missing tests)
- All 182 tests pass, ruff clean

### Session 6 (plan-13, Phase 5.5 + 6.2-6.5 + 7)
- Added admin DM NL routing in `router.py`: admin free text in DM now goes through Brain NL (contractors tool available)
- Routing priority preserved: commands > admin reply-to > FSM > admin NL > contractor catch-all
- Added 11 new tests in `test_interact.py` (stub verification, type change, redirect source, esrc callbacks)
- Created `tests/test_contractors_tool.py` with 8 tests for all 5 tool actions
- Updated `docs/diagrams/brain-flows.md` with contractors tool
- Updated `autonomous/dev/external-todo.md` with Plan 13 deployment checklist
- Supervisor: removed unused `state` parameter from `_route_admin_dm_nl`
- Linter: promoted `_stream_with_thinking`/`_dispatch_nl_result` to public API in conversation_handlers.py, removed duplicate test
- Linter logged 3 moderate debt items (#22-#24)
- All 197 tests pass, ruff clean
- **Plan 13 is COMPLETE.** All phases (1-7) fully implemented and tested.

### Session 7 (maintenance — tests + bug fix)
- Added missing test `test_esrc_callback_link_uses_linked_contractor` in `test_interact.py` — verifies link: path uses linked contractor's display_name
- Found and fixed bug: `_find_contractor_in_sheets` in `contractor_repo.py` didn't search stub sheet, breaking `bind_telegram_id` for stubs
- Linter resolved "Missing tests for esrc_callback link: and stub: paths" debt item
- All 198 tests pass, ruff clean

## Known issues

_None._

## Pitfalls

- GoalRepo uses `_row_to_dict` helper (SELECT * → dict via cursor.description) — different from PermissionRepo's positional tuple unpacking
- `update_goal`/`update_task` use sentinel string `"NOW()"` to inject SQL NOW() — fragile if someone passes literal "NOW()" as data
- FakeDb goal methods replicate SQL behavior in Python — may drift if repo changes
