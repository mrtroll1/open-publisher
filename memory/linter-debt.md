# Linter Debt

## 2026-03-11 — Fuzzy matching & contractor interaction audit

### Moderate

1. **Double threshold in `find_contractor` vs `fuzzy_find`** (`contractor_repo.py:165-169`)
   `find_contractor` calls `fuzzy_find(query, contractors)` with default threshold 0.8, then *also* checks `matches[0][1] >= 0.8`. The inner threshold already filters, so the outer check is redundant. If someone changes one threshold they'll likely forget the other. Collapse into a single gate.

2. **Test imports private function** (`tests/test_fuzzy_matching.py:4`)
   `_word_independent_score` is imported directly. If the scoring internals change, the test breaks for the wrong reason. Prefer testing through the public `fuzzy_find` interface, or promote the function by dropping the underscore since it is now part of the tested contract.

### Minor

3. **`_normalize_words` could be inlined** (`contractor_repo.py:115-117`)
   It is a one-liner called from exactly one place (`_word_independent_score`). Extracting it adds a name but no reuse. Acceptable either way — flag only if the file grows.

## 2026-03-11 — Stub Contractors audit

### Moderate

4. **`StubContractor` inherits bank fields it never uses** (`models.py:277-312`)
   `Contractor` base has required fields `email`, `bank_name`, `bank_account`. `StubContractor` must pass empty strings for all of them. If `Contractor` gains more financial fields, `StubContractor` must add more empty strings. Consider either giving these fields defaults in the base class or introducing a `NameOnlyContractor` base without financial fields.

5. **`_parse_stub` duplicates `_common_fields` partially** (`contractor_repo.py:100-117`)
   `_parse_stub` manually extracts `role_code`, `aliases`, `telegram`, `secret_code` — the same fields `_common_fields` provides plus hardcoded empty bank fields. Could call `_common_fields(row)` and override the bank fields, reducing duplication.

6. **`StubContractor.currency` raises `NotImplementedError`** (`models.py:294-295`)
   Any code that iterates contractors and calls `.currency` will blow up on stubs. This is a latent runtime error. Either return a sentinel value, or make `currency` `Optional` in the base so the type system catches it.

7. **No test for `ContractorFactory.upgrade_from_stub`** (`commands/contractor/create.py`)
   The new public method that replaces stub with full contractor has no unit test. Should test: stub alias preservation, sheet delete + save, ID reuse.

8. **No test for `ContractorFactory.create_stub`** (`commands/contractor/create.py`)
   Public method with no test coverage.

### Minor

9. **`ContractorHandlers` keeps growing** (`interact/contractor.py` ~640 lines)
   Already flagged in MEMORY.md. The stub-upgrade flow added another private method. Consider extracting registration-related handlers into a `RegistrationHandlers` class.

10. **`all_names` pattern repeated across 4 subclasses** (`models.py`)
    `GlobalContractor`, `IPContractor`, `SamozanyatyContractor`, `StubContractor` all have the same `all_names` pattern: prepend a name field, extend with aliases. Could be a base method parameterized by a `_name_field` attribute.

## 2026-03-11 — Contractor Type Change audit

### Moderate

11. **`change_contractor_type` is non-atomic: delete before save** (`contractor_repo.py:356-375`)
    If `save_contractor` fails (sheets API error, validation, etc.) after `delete_contractor_from_sheet` succeeds, the contractor is lost. Same pattern exists in `upgrade_from_stub` — both should save-then-delete, or at minimum catch and re-insert on failure.

12. **No test for `change_contractor_type`** (`contractor_repo.py:347-377`)
    Public function with no unit test. Should test: old row deleted, new row saved with correct type, preserved fields (id, aliases, telegram, secret_code, mags), reset fields (invoice_number=0), type-specific fields populated from new_data.

13. **No test for `change_type` handler or `_execute_type_change`** (`interact/contractor.py:247-264, 485-489`)
    The new handler flow (menu button -> type selection -> data input -> type change) has no integration test. At minimum: test that `menu_callback` with `"menu:change_type"` starts the flow, test that `_complete_registration` with `changing_type_id` in fsm_data calls `change_contractor_type`.

14. ~~**`_execute_type_change` raises bare `ValueError` on missing contractor**~~ — **FIXED** in this audit. Now returns `None`, caller shows user-friendly message.

### Minor

15. **`ContractorHandlers` now ~660 lines** (`interact/contractor.py`)
    Continues to grow (see item 9). The type-change flow adds another public handler + private helper. The class now has 15 public handlers — well past the "a few publics max" threshold.

## 2026-03-12 — Contractors tool & article rate rules audit

### Moderate

16. **`contractors.py` actions each call `load_all_contractors()` independently** (`brain/tools/contractors.py:27,43,57,73,85`)
    Every action function loads all contractors from the Google Sheet. The dispatch function (`fn`) could load once and pass the list to each action, like `goals.py` passes `db` and `gemini`. This avoids 1 redundant sheet API call per invocation and makes the dependency explicit.

17. **Sheet name duplicated between range constant and row-level writes** (`rules_repo.py`)
    `_ARTICLE_RATE_RANGE` defines `"'per_article_rate_rules'!A:Z"` but `upsert_article_rate_rule` hardcodes `f"'per_article_rate_rules'!A{i}:C{i}"`. Same pre-existing pattern in `remove_redirect_rule` with `_REDIRECT_RANGE`. Extract a helper like `_row_range(sheet_name, row, cols)` or at minimum derive the sheet prefix from the constant.

18. **No tests for `make_contractors_tool` or its actions** (`brain/tools/contractors.py`)
    Five public actions (`lookup`, `create_stub`, `add_redirect`, `set_rate`, `get_rate`) with no test coverage. The tool touches sheets and contractor factory — at minimum mock-based tests for the dispatch and error paths.

19. **No tests for `upsert_article_rate_rule` or `get_article_rate_rule`** (`rules_repo.py`)
    Two new public functions with no test coverage. `upsert` has branching logic (empty sheet, existing row, new row) that warrants unit tests.

### Minor

20. **`_ctx` unused in contractors tool dispatch** (`brain/tools/contractors.py:105`)
    The context is ignored — none of the actions use it. This is fine for now since the tool relies on DB-level permissions, but if any action needs user context later, the plumbing is already there.

21. **Migration 008 `ON CONFLICT DO NOTHING` is safe but silent** (`migrations/008_editor_dm_environment.sql:12`)
    If the `tool_permissions` rows already exist with *different* `allowed_roles`, the migration silently keeps the old values. This matches migration 006's pattern but could mask permission drift. Acceptable for seed data.
