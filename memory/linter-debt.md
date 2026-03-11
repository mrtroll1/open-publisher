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
