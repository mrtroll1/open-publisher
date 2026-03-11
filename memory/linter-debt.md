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
