# Dev Agent Memory

> This file accumulates context across autonomous sessions. The orchestrator updates it after each session.

## Session Log

### Session 1 (2026-03-01) — Feature 6: Postgres + Email Thread Tracking
**Status:** Complete (all 7 steps)

**What was done:**
- Added Postgres (`pgvector/pgvector:pg16`) to `docker-compose.yml` with `pgdata` volume
- Added `DATABASE_URL` env var to `common/config.py`
- Created `backend/infrastructure/gateways/db_gateway.py` — `DbGateway` class with:
  - `email_threads` and `email_messages` tables (auto-created via `init_schema()`)
  - Thread finding by `in_reply_to` header or normalized subject matching
  - Message persistence with ON CONFLICT dedup on `message_id`
  - Thread history retrieval ordered by `created_at`
- Added `in_reply_to` and `references` fields to `IncomingEmail` model
- Updated `email_gateway.py` to parse `In-Reply-To` and `References` headers
- Integrated thread tracking into `SupportEmailService`:
  - Finds/creates thread on each inbound email
  - Saves inbound + outbound messages to DB
  - Formats thread history as context for LLM drafting
  - Uses existing `support_email_with_context()` compose function
- Added `psycopg2-binary>=2.9,<3` to `requirements.txt`
- Added `DB_PASSWORD` and `DATABASE_URL` to `config/example/.env`

**Notes:**
- `DbGateway` uses `autocommit=True` and lazy reconnection
- Subject normalization strips Re:/Fwd:/Fw: prefixes, case-insensitive
- `find_thread()` does a full scan for subject matching — acceptable for current volume
- Outbound messages saved with `message_id=""`, works because ON CONFLICT checks `message_id` unique constraint
- `_uid_thread` dict maps Gmail uid → thread_id for tracking between `_draft()` and `approve()`

### Session 2 (2026-03-01) — Feature 1: Linked User Menu
**Status:** Complete (all 7 steps)

**What was done:**
- Added `linked_menu` reply strings class to `telegram_bot/replies.py`
- Added `waiting_update_data` FSM state to contractor flow in `telegram_bot/flows.py`
- Modified `handle_contractor_text` to show inline menu for linked (non-admin) users
- Modified `handle_start` to show linked menu on /start for linked contractors (admins still get admin menu)
- Created `handle_linked_menu_callback` for `menu:` prefix — dispatches to `menu:contract` (deliver invoice) and `menu:update` (enter update flow)
- Created `handle_update_data` — parses free-form text with LLM, updates contractor fields in sheet
- Created `update_contractor_fields()` in contractor_repo.py — cell-by-cell writes for arbitrary field updates
- Re-exported `update_contractor_fields` from `backend/__init__.py`
- Registered `menu:` callback handler in `telegram_bot/main.py`

**Review fixes applied:**
- Fixed admin-vs-contractor priority in `handle_start` — admins checked first, then contractor lookup
- Fixed same issue in `handle_contractor_text` — admins skip linked menu, fall through to name lookup
- Added explicit `parse_error` check in `handle_update_data` before building updates dict

**Notes:**
- `menu:editor` button is NOT included yet — reserved for Feature 2
- Update flow reuses `_parse_with_llm` from registration — same LLM parsing, just applied to update context
- `update_contractor_fields` does individual cell writes per field (not batch) — acceptable for low volume

### Session 3 (2026-03-01) — Feature 2: Editor Source Management
**Status:** Complete (all 6 steps)

**What was done:**
- Added `editor_sources` reply strings class to `telegram_bot/replies.py`
- Added 3 CRUD functions to `rules_repo.py`: `find_redirect_rules_by_target`, `add_redirect_rule`, `remove_redirect_rule`
- Extracted `_REDIRECT_RANGE` constant in rules_repo to avoid repetition
- Created `_linked_menu_markup(contractor)` helper in `flow_callbacks.py` — builds inline keyboard with 2 or 3 buttons depending on `contractor.role_code == RoleCode.REDAKTOR`
- Both `handle_start` and `handle_contractor_text` now use `_linked_menu_markup`
- Added `menu:editor` handling in `handle_linked_menu_callback` → dispatches to `_show_editor_sources()`
- Created `_editor_sources_content(rules)` helper — returns `(text, InlineKeyboardMarkup)` for the source list view
- Created `_show_editor_sources(callback, contractor)` — renders source list via `edit_text`
- Created `handle_editor_source_callback` for `esrc:` prefix — handles list/rm/add/back actions
- Created `handle_editor_source_name` — handles text input for adding a new source, shows updated list via `message.answer`
- Added `waiting_editor_source_name` FSM state to contractor flow
- Registered `esrc:` callback handler in `main.py` (before `menu:` handler)
- Re-exported 3 rules_repo functions from `backend/__init__.py`

**Review fixes applied:**
- Extracted `_editor_sources_content()` helper to eliminate duplicated keyboard-building logic between `_show_editor_sources` and `handle_editor_source_name`
- Fixed double `callback.answer()` bug in `handle_editor_source_callback` — was called unconditionally at top AND again in `rm:` branch (Telegram only allows one answer per callback)

**Notes:**
- `remove_redirect_rule` uses `_sheets.clear()` (clears cell contents, preserves row) — leaves blank rows in the sheet. Acceptable for now.
- `add_redirect_rule` always sets `add_to_total=TRUE`
- No validation that source_name exists in budget table — editor can add any name. Validation can be added later.
- Callback data for remove: `esrc:rm:{source_name}` — Telegram limits callback_data to 64 bytes, but author names are well within this.

### Session 4 (2026-03-01) — Feature 3: Redefine PNL + Exchange Rate → Budget Sheet
**Status:** Complete (all 5 steps)

**What was done:**
- Added 4 env vars to `common/config.py`: `PNL_API_URL`, `PNL_API_USER`, `PNL_API_PASSWORD`, `EUR_RUB_CELL`
- Added `get_pnl_stats(month)` to `RedefineGateway` — uses separate base URL (`PNL_API_URL`) and HTTP Basic auth, independent from support API
- Created `backend/infrastructure/gateways/exchange_rate_gateway.py` — single `fetch_eur_rub_rate()` function using `open.er-api.com` (free, no key)
- Modified `ComputeBudget.execute()` to fetch EUR/RUB rate and PNL data, then call `write_pnl_section()` after main entries
- Added `_build_pnl_rows()` static method — builds rows with EUR formula `=ROUND(rub/$G$2, 0)` and plain RUB amount
- Added `write_pnl_section()` to `budget_repo.py` — writes rate to `EUR_RUB_CELL` and PNL rows below main entries
- Updated `config/example/.env` with PNL env vars

**Orchestrator fixes applied:**
- Fixed `EUR_RUB_CELL` config var being defined but not imported/used — now `budget_repo.py` imports and uses it instead of hardcoding `"G2"`
- Fixed formula reference in `_build_pnl_rows` to derive `$G$2` from `EUR_RUB_CELL` dynamically
- Moved absolute reference conversion out of the per-item loop

**Notes:**
- PNL API response format assumed: `{"data": {"items": [{"name": "...", "category": "...", "amount": 123456}]}}` — needs verification against real API
- Graceful failures: PNL URL not configured → skip PNL; API error → skip PNL; rate fetch fails → 0.0, skip PNL rows (avoids #DIV/0!)
- No new re-exports in `backend/__init__.py` — `ComputeBudget` is already exported
- `SheetsGateway.write()` defaults to `USER_ENTERED` so formula strings are auto-interpreted

## Known patterns

- **Gateway pattern**: Infrastructure gateways live in `backend/infrastructure/gateways/`. Each wraps an external service (Gmail, Gemini, Google Sheets, now Postgres).
- **Service pattern**: Domain services in `backend/domain/` orchestrate gateways. `SupportEmailService` is the main email orchestrator.
- **Config pattern**: All env vars defined in `common/config.py` with sensible defaults. Example values in `config/example/.env`.
- **Re-exports**: `backend/__init__.py` re-exports only what the telegram bot needs. Internal components (like `DbGateway`) stay private.
- **Compose pattern**: LLM prompts built via `compose_request.py` functions. Templates in `templates/` dir. `support_email_with_context()` adds user data + thread history to the `{{USER_DATA}}` placeholder.
- **Callback data pattern**: Prefixed strings like `dup:`, `email:`, `menu:`, `esrc:`. Registered in `main.py` with `F.data.startswith("prefix:")`.
- **FSM state string pattern**: `"ContractorStates:state_name"` — built from flow name title-cased + "States". Used in callback handlers to set state programmatically.
- **Admin priority**: In handlers that serve both admins and contractors, always check `is_admin()` first. Admins should not see contractor menus.

## Known issues

_None yet._

## Pitfalls

- `IncomingEmail.uid` is a Gmail message ID (volatile across sessions). Don't use it as a durable DB key — use `message_id` (RFC Message-ID header) instead.
- The `_pending` dict in `SupportEmailService` is ephemeral — lost on restart. Thread history in Postgres survives restarts, but pending drafts don't.

### Session 5 (2026-03-01) — Feature 4: Article Proposal Monitoring
**Status:** Complete (all 6 steps)

**What was done:**
- Added `CHIEF_EDITOR_EMAIL` env var to `common/config.py` and `config/example/.env`
- Created `backend/domain/article_proposal_service.py` — `ArticleProposalService` class with:
  - `process_proposals(emails)` — iterates over non-support emails, runs LLM triage, forwards legit proposals
  - `_is_legit_proposal(email)` — calls Gemini with article proposal triage prompt
  - `_forward(email)` — forwards email to chief editor via `EmailGateway.send_reply()`
  - Short-circuits if `CHIEF_EDITOR_EMAIL` is not configured (returns empty list)
- Created `templates/article-proposal-triage.md` — LLM prompt with criteria for identifying article proposals vs spam/support/commercial
- Added `article_proposal_triage()` compose function and model entry to `compose_request.py`
- Modified `SupportEmailService.fetch_new_drafts()` to collect non-support emails into `_non_support` buffer
- Added `fetch_non_support()` method to `SupportEmailService` — returns and clears the buffer
- Extended `email_listener_task` to:
  - Fetch non-support emails after processing support drafts
  - Run them through `ArticleProposalService.process_proposals()`
  - Notify admin via Telegram for each forwarded proposal
  - Mark all non-support emails as read via `skip()`
- Imported `ArticleProposalService` directly in `flow_callbacks.py` (same pattern as `SupportEmailService`)
- Added re-export in `backend/__init__.py`

**Notes:**
- `ArticleProposalService` uses its own `EmailGateway` instance (separate from `SupportEmailService`'s) — both share the same Gmail credentials
- `_forward()` sends a new email to chief editor (not a Gmail forward), containing the original email body with From/Subject/Date metadata
- Non-support emails are marked as read regardless of whether they were forwarded — this prevents re-processing on next poll
- If `CHIEF_EDITOR_EMAIL` is empty, `process_proposals()` returns `[]` immediately — no LLM calls made

### Session 6 (2026-03-01) — Feature 5: Repo Access for Tech Support
**Status:** Complete (Steps 5.1–5.5, Step 5.6 deferred)

**What was done:**
- Added 4 env vars to `common/config.py`: `REPOS_DIR`, `REPUBLIC_REPO_URL`, `REDEFINE_REPO_URL`, `ANTHROPIC_API_KEY`
- Created `backend/infrastructure/gateways/repo_gateway.py` — `RepoGateway` class with:
  - `ensure_repos()` — shallow clone (`--depth 1`) or pull (`--ff-only`) for each configured repo
  - `search_code(query, repo)` — subprocess grep across repos, returns up to 20 `(rel_path, lineno, content)` tuples
  - `read_file(repo, filepath, max_lines)` — reads file from a repo dir
  - All operations no-op gracefully if no repo URLs configured
- Created `templates/tech-search-terms.md` — Russian-language LLM prompt to extract search terms and `needs_code` flag
- Added `tech_search_terms()` compose function to `compose_request.py` with model entry
- Modified `SupportEmailService`:
  - Init: creates `RepoGateway`, calls `ensure_repos()` on startup
  - Added `_fetch_code_context(email_text)` — LLM extracts terms → grep repos → read top 5 files → format as markdown code snippets
  - Modified `_draft()` — code_context appended as third component alongside user_data and thread_context
- Modified `Dockerfile`: added `git` installation via apt-get
- Modified `docker-compose.yml`: added `./repos:/opt/repos` bind mount to bot service
- Updated `config/example/.env` with new env vars

**Notes:**
- `RepoGateway` is internal to `SupportEmailService`, NOT re-exported in `backend/__init__.py`
- Repos cloned to `REPOS_DIR` (default `/opt/repos`), named "republic" and "redefine" (hardcoded from URLs)
- `ANTHROPIC_API_KEY` env var added but unused — reserved for future Step 5.6 (Claude Code subprocess)
- `_fetch_code_context()` wraps everything in try/except, returns "" on any failure — never blocks email drafting
- Code snippets are ~50 lines centered around the grep match (25 lines above/below)
- `search_code` includes common file extensions: .py, .js, .ts, .html, .css, .yml, .yaml, .json, .md

### Session 7 (2026-03-01) — Maintenance: Write Tests
**Status:** Complete

**What was done:**
- Added `pytest>=7,<9` to `requirements.txt`
- Created `tests/` directory with `__init__.py` and `conftest.py` (adds project root to sys.path)
- Created `tests/test_db_gateway.py` — 16 parametrized tests for `_normalize_subject()`:
  - Re/Fwd/Fw prefix stripping, case insensitivity, nested prefixes, whitespace, empty string, non-prefix words
- Created `tests/test_compute_budget.py` — 37 tests across 5 test classes:
  - `TestComputeBudgetAmount` (9 tests): flat, rate, default rate, edge cases
  - `TestTargetMonthName` (6 tests): month+2 mapping with wrap-around
  - `TestRoleLabel` (4 tests): role_code → label mapping
  - `TestBuildPnlRows` (8 tests): PNL formula generation, empty/zero guards, skipping invalid items
  - `TestRouteEntry` (11 tests): entry routing to correct group by label/role/flat_ids
- All 53 tests pass in 0.31s

**Notes:**
- Tests focus on pure-logic functions with zero external dependencies (no mocking needed)
- Helper functions `_global()` and `_samoz()` create minimal contractor instances for tests
- Future sessions can add tests for service-layer code (requires mocking gateways)

### Session 8 (2026-03-01) — Maintenance: Spot Bugs
**Status:** Complete

**What was done:**
- Thorough code review across all 6 implemented features, covering:
  - DB gateway + support email service + repo gateway
  - Telegram bot flows, callbacks, handler registration
  - Budget computation, PNL integration, exchange rates
  - Article proposal service, compose request, contractor/rules repos
- Found and fixed 3 confirmed bugs in `telegram_bot/flow_callbacks.py`:
  1. **`tmp_path` uninitialized in finally block** (line ~1114-1135): If `NamedTemporaryFile()` threw before `tmp_path` was assigned, the finally block would crash with `NameError`. Fixed by initializing `tmp_path = None` before try and adding `if tmp_path:` guard.
  2. **Dead code `esrc:list`** (line ~728): Handler for `data == "list"` was unreachable — no callback ever generates `esrc:list`. Removed the dead block.
  3. **`ADMIN_TELEGRAM_IDS[0]` without empty check** (line ~1151): `email_listener_task()` would crash with `IndexError` if admin IDs list was empty. Added early-return guard with warning log.
- Several other reported findings were verified as false positives:
  - Rate selection logic `(rate_tuple[0] or rate_tuple[1])` is correct — rates are mutually exclusive per contractor
  - `return "done"` from FSM handlers matches transition keys in `flows.py`
  - Off-by-one in code snippet line numbers is actually correct (exclusive end index maps to 1-indexed display)

**Notes:**
- Tests can't run locally due to missing `google.oauth2` dependency (deployment-only). Pre-existing issue.
- Future sessions can add mocking to fix local test execution.

### Session 9 (2026-03-01) — Maintenance: Refactor
**Status:** Complete

**What was done:**
- Extracted duplicated utility functions to shared module:
  - Created `backend/infrastructure/repositories/sheets_utils.py` with `index_to_column_letter()` and `parse_int()`
  - Removed duplicate `_index_to_column_letter` from `contractor_repo.py` and `invoice_repo.py`
  - Removed duplicate `_parse_int` from `rules_repo.py` and `budget_repo.py`
  - Updated all call sites and imports in 4 repo files
- Extracted duplicated blocks in `telegram_bot/flow_callbacks.py`:
  - `_start_invoice_flow()` — extracted from `handle_verification_code` and `_finish_registration` (budget fetch → amount prompt logic)
  - `_notify_admins_rub_invoice()` — extracted from `_deliver_existing_invoice` and `handle_amount_input` (RUB invoice admin notification)
- Moved inline imports to top of `flow_callbacks.py`: `os`, `tempfile`, `ComputeBudget`, `ParseBankStatement`
- Added `as_text()` method to `IncomingEmail` model in `common/models.py`
- Updated `support_email_service.py` and `article_proposal_service.py` to use `email.as_text()`
- Fixed `set_data` → `update_data` behavioral change: added explicit `state.clear()` before `_start_invoice_flow` in verification path to preserve original state-clearing behavior

**Net result:** -42 lines, 6 duplicated code blocks eliminated across 9 files

**Notes:**
- `_start_invoice_flow` returns None when no articles found (callers handle messaging/state clearing themselves)
- `_notify_admins_rub_invoice` takes `pdf_bytes, filename, contractor, month, amount` — used by both existing invoice delivery and new contractor invoice generation
- The `SupportEmailService` and `ArticleProposalService` module-level imports in flow_callbacks.py were left in place (they create instances immediately below)

### Session 10 (2026-03-01) — Maintenance: Polish UX
**Status:** Complete

**What was done:**
- Translated all English email-related bot messages to Russian (4 strings in email callback handler + proposal notification)
- Added cancel support ("отмена" / "/cancel") for `waiting_update_data` and `waiting_editor_source_name` FSM states — users previously had no way to exit these except /start
- Moved 10+ hardcoded Russian strings from `flow_callbacks.py` to `replies.py`:
  - `lookup.new_contractor_btn` — "Я новый контрагент" button
  - `admin.batch_generating`, `admin.batch_no_new`, `admin.not_in_budget`, `admin.zero_amount` — batch generation messages
  - `document.forwarded_to_admin`, `document.forwarded_drive` — document forwarding captions
  - `notifications.contractor_linked`, `notifications.new_registration`, `notifications.new_registration_parsed` — admin notifications
- Improved admin email draft display:
  - `can_answer: True/False` → "Черновик ответа" / "Черновик ответа (⚠ не уверен в ответе)"
  - "Send"/"Skip" buttons → "Отправить"/"Пропустить"
- Added two new reply classes: `email_support` and `notifications`

**Notes:**
- Cancel strings are inline in flow_callbacks.py (not in replies.py) since they're one-off short responses
- `_send_email_draft` From/Subject/Reply-To headers still in English (intentional — email metadata is typically displayed in English)
- Updated prompt strings include cancel hint: `update_prompt` and `add_prompt` now mention "отмена"

### Session 11 (2026-03-01) — Maintenance: Improve Prompts
**Status:** Complete

**What was done:**
- Fixed critical bug in `knowledge/tech-support.md`: `{{SUBSCRIPTION_RSERVICE_URL}}` → `{{SUBSCRIPTION_SERVICE_URL}}` in 4 places. The extra "R" meant the subscription URL was never injected into support email LLM prompts — the LLM was seeing raw template variables instead of actual URLs.
- Fixed 10+ Russian typos across `knowledge/base.md`, `knowledge/tech-support.md`, and `templates/support-email.md`
- Improved `templates/support-email.md`:
  - Clearer `can_answer` criteria (knowledge base has info for confident answer vs. answer would be a guess)
  - Added: always write best possible reply even when `can_answer=false` (helps admin reviewer)
  - Explicit that `reply` should be full ready-to-send email text
- Improved `templates/tech-search-terms.md`:
  - Added `needs_code` default guidance: false for user questions (subscriptions, payments, accounts), true only for potential code bugs
  - Added 4 concrete examples
- Improved `templates/support-triage.md`:
  - Added: use empty string "" for `lookup_email` when no user email can be identified
  - Added: automated system emails should get empty needs and empty lookup_email

**Notes:**
- The SUBSCRIPTION_RSERVICE_URL bug was likely degrading support email quality since the LLM lacked the actual redefine.media URL for referencing subscription management links
- All prompt improvements are backward-compatible — no code changes needed, only template/knowledge file edits

### Session 12 (2026-03-01) — Maintenance: Write Tests (round 2)
**Status:** Complete

**What was done:**
- Created `tests/test_resolve_amount.py` — 30 tests across 4 classes:
  - `TestPluralRu` (18 parametrized): Russian plural forms for all corner cases (1, 2-4, 5+, 11-19 special, 21, 100, 101, 111)
  - `TestFmt` (5 tests): thousand separator formatting
  - `TestFormatBudgetExplanation` (7 tests): budget breakdown with/without bonus notes
  - `TestResolveAmount` (7 tests): budget lookup, fallback rates, EUR/RUB handling
- Created `tests/test_validate_contractor.py` — 30 tests across 4 classes:
  - `TestDigitsOnly` (4 tests): digit extraction helper
  - `TestValidateSamozanyaty` (19 tests): passport, INN, bank account, BIK, address, email validation
  - `TestValidateIP` (4 tests): OGRNIP + inherited validations
  - `TestValidateGlobal` (11 tests): SWIFT, IBAN, Latin address, email
- Created `tests/test_contractor_repo.py` — 27 tests across 8 classes:
  - `TestSimilarity` (5), `TestFuzzyFind` (7), `TestFindContractorById` (3), `TestFindContractorStrict` (3), `TestFindContractorByTelegramId` (2), `TestNextContractorId` (3), `TestContractorToRow` (4), `TestParseContractor` (8)
- **Fixed pre-existing conftest.py issue**: Added `sys.modules.setdefault()` stubs for `googleapiclient` and `psycopg2` — tests now run locally without deployment dependencies

**Net result:** 87 new tests (167 total), all passing in 0.29s

**Notes:**
- conftest.py now stubs `googleapiclient`, `googleapiclient.discovery`, `googleapiclient.http`, and `psycopg2` using MagicMock
- Tests are pure-logic only — no network calls, no mocking of services
- `_parse_contractor` always defaults missing fields to "" via `row.get(field, "")`, so Pydantic ValidationError never triggers for missing keys
- Future: consider testing `parse_bank_statement.py` helpers (need to handle config dependency), service-layer code with mocked gateways

### Session 13 (2026-03-01) — Maintenance: Spot Bugs (round 2)
**Status:** Complete

**What was done:**
- Thorough code review across all files modified in sessions 9-12 (refactor, UX, prompts, tests)
- Found and fixed 3 issues:

1. **CONFIRMED BUG — Currency-blind flat/rate selection in `compute_budget.py`**:
   - `flat_by_id` stored `fr.eur or fr.rub` (single int), losing currency distinction
   - `rate` selection used `(rate_tuple[0] or rate_tuple[1])` — always picks EUR if non-zero, regardless of contractor's actual currency
   - **Fix**: `flat_by_id` now stores `(eur, rub)` tuple; selection uses `c.currency == Currency.EUR` to pick the correct value
   - **Impact**: Could have assigned wrong-currency amounts to contractors with both EUR and RUB values configured

2. **DEAD CODE — `/cancel` check in FSM text handlers** (flow_callbacks.py):
   - `handle_editor_source_name` and `handle_update_data` checked for `/cancel` in text input
   - But `flow_engine.py:138` filters out `/`-prefixed messages (`F.text & ~F.text.startswith("/")`) — `/cancel` would never reach these handlers
   - **Fix**: Removed unreachable `/cancel` check, kept only "отмена"

3. **TEST FIX — `flat_ids` type mismatch**:
   - `test_no_label_in_flat_ids_to_staff` passed `{"g1": 500}` but `_route_entry` now expects `dict[str, tuple[int, int]]`
   - Fixed to `{"g1": (500, 0)}`

**Notes:**
- The currency bug was incorrectly classified as "false positive" in session 8 ("rates are mutually exclusive per contractor"). While rates may typically be mutually exclusive in practice, the `or` logic was fragile and incorrect for edge cases
- All 167 tests pass after fixes

### Session 14 (2026-03-01) — Maintenance: Refactor (round 2)
**Status:** Complete

**What was done:**
- Extracted `_write_cell()` helper in `contractor_repo.py` — encapsulates column lookup + cell address building + write pattern
- Simplified `bind_telegram_id` — replaced 7-line manual column/cell/write block with single `_write_cell` call
- Simplified `increment_invoice_number` — replaced manual cell write with `_write_cell`, kept read-current-value logic
- Simplified `update_contractor_fields` — replaced 8-line for-loop with `sum()` expression over `_write_cell` calls
- Extracted `_find_invoice_row()` helper in `invoice_repo.py` — encapsulates read rows + parse headers + find matching row
- Simplified `update_invoice_status` — reduced from 25 to 15 lines
- Simplified `update_legium_link` — reduced from 28 to 16 lines

**Net result:** -17 lines, 5 duplicated code blocks eliminated across 2 files

**Notes:**
- All 167 tests pass
- No function signatures or public behavior changed
- `_write_cell` returns bool so callers can branch on success/failure
- `_find_invoice_row` returns `(headers, row_idx)` tuple so callers can still resolve additional columns

### Session 15 (2026-03-01) — Maintenance: Polish UX (round 2)
**Status:** Complete

**What was done:**
- Moved 7 hardcoded Russian strings from `flow_callbacks.py` to `replies.py`:
  - `registration.progress_header`, `registration.still_needed`, `registration.send_corrections` — registration progress messages
  - `registration.complete_summary`, `registration.complete_secret` — registration completion
  - `linked_menu.update_cancelled`, `editor_sources.add_cancelled` — cancel confirmations
- Added `generic.text_expected` reply string class
- **Non-text input in FSM states**: `handle_non_document` now checks `state.get_state()` first — if user is in an active FSM state, replies "Пожалуйста, отправьте текстовое сообщение." instead of silently dropping the message
- **Audio filter**: Added `F.audio` to non-document handler filter in `main.py` (was missing)
- **Stale callback protection**: Wrapped 7 `edit_text()`/`delete()` call sites in `TelegramBadRequest` try/except across 4 handlers (`handle_duplicate_callback`, `_show_editor_sources`, `handle_editor_source_callback`, `handle_email_callback`)
- **Defensive None-safety**: Added `message.text and` guard before `.strip().lower()` in cancel checks in `handle_editor_source_name` and `handle_update_data`
- **Typing indicator**: Added `ChatAction.TYPING` before contract delivery in `handle_linked_menu_callback` (Google Sheets/Drive fetch can be slow)

**Notes:**
- Tone review confirmed consistent formal "вы" for contractors, casual for admins — no changes needed
- All 167 tests pass

### Session 16 (2026-03-01) — Maintenance: Improve Prompts (round 2)
**Status:** Complete

**What was done:**
- Expanded `knowledge/payment-data-validation.md` from 3 lines to comprehensive format reference:
  - Added digit-extraction instruction for numeric fields
  - Added "Форматы полей: самозанятый / ИП" section with 11 field format rules (matching validate_contractor.py checks)
  - Added "Форматы полей: global" section with 5 international field format rules
- Improved `templates/contractor-parse.md`:
  - Added digit-only extraction rule for numeric fields
  - Added ФИО reordering instruction (Имя Фамилия → Фамилия Имя Отчество)
  - Added "don't hallucinate missing values" instruction
- Improved `templates/translate-name.md`:
  - Handle already-Cyrillic names (return as-is)
  - Phonetic transliteration fallback for names with no standard translation
  - Preserve original word order
- Improved `templates/article-proposal-triage.md`:
  - Added "press releases and PR mailings" to negative criteria
  - Added 4 concrete examples (2 true, 2 false) matching tech-search-terms pattern
- Improved `templates/support-email.md`:
  - Added first-person voice instruction (no "наша команда техподдержки")
  - Added email signature convention: "С уважением, Иван Добровольский, Republic"

**Notes:**
- All changes are content-only (templates + knowledge files), no code changes
- All 167 tests pass
- payment-data-validation.md now mirrors validate_contractor.py rules — LLM should extract cleaner data on first pass, reducing validation warnings

### Session 17 (2026-03-01) — Maintenance: Write Tests (round 3)
**Status:** Complete

**What was done:**
- Created `tests/test_parse_bank_statement.py` — 30 tests across 7 classes:
  - `TestToRub` (9): AED-to-RUB conversion, rounding, zero/large amounts
  - `TestFormatDate` (6): ISO date validation, invalid formats returned as-is
  - `TestMonthLabel` (7): month name extraction, invalid/empty input fallback
  - `TestBo` (3): backoffice unit shorthand
  - `TestClassifyPerson` (4): known people lookup from config, unknown defaults
  - `TestIsOwner` (5): owner keyword matching, case sensitivity
  - `TestMatchService` (8): service matching by substring, case-insensitive, split flag
- Created `tests/test_invoice_repo.py` — 26 tests across 3 classes:
  - `TestRowToInvoice` (15): valid/missing fields, all enum values, defaults
  - `TestInvoiceToRow` (8): serialization, all status/currency enums
  - `TestRoundtrip` (2): bidirectional row↔invoice consistency
- Created `tests/test_sheets_utils.py` — 21 tests across 2 classes:
  - `TestIndexToColumnLetter` (11): single/double/triple letter columns, progression
  - `TestParseInt` (10): valid/invalid/edge cases
- Created `tests/test_models.py` — 20 tests across 5 classes:
  - `TestRequiredFields` (5): all contractor subclasses + base
  - `TestAllFieldLabels` (5): field count matches FIELD_META, subset check
  - `TestFieldNamesCsv` (4): CSV output for all subclasses
  - `TestIncomingEmailAsText` (5): formatting, unicode, excluded fields

**Net result:** 87 new tests (274 total), all passing in 0.35s

**Notes:**
- `test_parse_bank_statement.py` tests use real business config values (KNOWN_PEOPLE, OWNER_KEYWORDS, SERVICE_MAP) — tests will catch unintended config changes
- `test_invoice_repo.py` has roundtrip tests verifying row→invoice→row and invoice→row→invoice consistency
- No conftest.py changes needed — existing stubs sufficient
- Pure-logic coverage now comprehensive. Remaining untested areas are service-layer code (requires mocked gateways) and email parsing

### Session 18 (2026-03-01) — Maintenance: Spot Bugs (round 3)
**Status:** Complete

**What was done:**
- Thorough code review across 30+ files in all layers (domain, infrastructure, telegram bot)
- Found and fixed 3 confirmed bugs:

1. **Forwarded article proposals get "Re:" prefix** (`email_gateway.py`):
   - `send_reply()` only checked for `"Re:"` prefix before prepending it
   - `ArticleProposalService._forward()` passes subjects like `"Fwd: Some Article"` which got mangled to `"Re: Fwd: Some Article"`
   - **Fix**: Added `"Fwd:"` and `"Fw:"` prefix checks alongside `"Re:"`

2. **`pop_random_secret_code()` could select header row** (`contractor_repo.py`):
   - Function iterated over ALL rows from `secret_codes!A:A` including index 0 (header)
   - Header text like "secret_code" could be randomly selected as a contractor's code, and cleared from the sheet
   - **Fix**: Added `i > 0` filter to skip header row

3. **Debug mode saved invoices to sheet, blocking real generation** (`generate_invoice.py`):
   - Docstring stated "In debug mode, skips number increment and sheet save"
   - But only number increment was skipped — `save_invoice()` was called unconditionally
   - Running `/generate_invoices debug` would create records with `invoice_number=0`, which then prevented real generation (contractor already had an invoice entry)
   - **Fix**: Wrapped `save_invoice()` in `if not debug:`

**Notes:**
- All 274 tests pass after fixes
- Bug 3 (debug mode) is the most impactful — could silently block real invoice generation after a debug run

### Session 19 (2026-03-01) — Maintenance: Refactor (round 3)
**Status:** Complete

**What was done:**
- Extracted `_generate_rub_invoice()` helper in `generate_invoice.py` — unified `_generate_ip()` and `_generate_samozanyaty()` which shared 14 identical template replacements. Each now only provides their unique fields via `extra_replacements` dict.
- Extracted `_write_invoice_field()` helper in `invoice_repo.py` — column lookup + write pattern, matching existing `_write_cell()` in contractor_repo. Used by `update_invoice_status()` and `update_legium_link()`.
- Extracted `_pick_by_currency()` helper in `compute_budget.py` — eliminated duplicated tuple→currency→value logic in two places within `_build_entries()`.
- Moved inline imports (`SupportEmailService`, `ArticleProposalService`) to top-of-file in `flow_callbacks.py`.
- Fixed duplicate `logger.info` line introduced during refactoring in `update_legium_link`.

**Net result:** -14 lines, 4 duplicated code blocks eliminated across 4 files

**Notes:**
- All 274 tests pass
- `_generate_rub_invoice` works for both IP and Samozanyaty — the shared fields (passport, bank, amount, dates) are identical
- No function signatures or public behavior changed

### Session 20 (2026-03-01) — Maintenance: Polish UX (round 3)
**Status:** Complete

**What was done:**
- Moved 9 hardcoded Russian strings from `flow_callbacks.py` to `replies.py`:
  - `lookup.selected` — duplicate selection confirmation
  - `admin.generate_caption` — single invoice document caption
  - `admin.batch_done`, `admin.batch_counts`, `admin.batch_no_generated`, `admin.batch_errors` — batch generation summary parts
  - `admin.send_global_done` — global send summary
  - `admin.upload_needs_review` — bank upload review warning
  - `invoice.delivery_error` — user-facing error when invoice delivery fails
- Added typing indicators in 2 places:
  - `cmd_generate_invoices`: before `GenerateBatchInvoices().execute` (long batch operation)
  - `_start_invoice_flow`: before Google Sheets calls (budget + articles lookup)
- Added error handling for invoice delivery failures:
  - `handle_linked_menu_callback` ("contract" action): wrapped `_deliver_existing_invoice` in try/except, shows friendly error message
  - `handle_verification_code` (post-verification): wrapped in try/except, sets `delivered=False` so flow falls through gracefully

**Notes:**
- All 274 tests pass
- Input matching patterns ("самозанятый", "ип", "отмена") were intentionally left inline — they're not user-facing messages
- `invoice.delivery_error` uses f-string with `ADMIN_TELEGRAM_TAG` at class definition time (same pattern as other reply classes)

### Session 21 (2026-03-01) — Maintenance: Improve Prompts (round 3)
**Status:** Complete

**What was done:**
- Reviewed all 12 template and knowledge files for remaining improvements
- Fixed 6 Russian typos/grammar errors across knowledge/base.md and knowledge/tech-support.md:
  - "просиходит" → "происходит", "эти задач...из можно" → "этих задач...их можно"
  - "Акканты" → "Аккаунты", "несвязаное" → "несвязанное", "читаешь" → "считаешь", "информации" → "информация"
- Improved templates/support-email.md:
  - Fixed "Быть внимателен" → "Будь внимателен" (imperative mood consistency)
  - Added instruction to extract user's name from From header for personalized greetings
- Improved templates/support-triage.md:
  - Added forwarded email handling: use end-user's address, not intermediary forwarders
- Improved templates/tech-search-terms.md:
  - Made explicit: return empty search_terms list when needs_code=false
- Improved templates/contractor-parse.md:
  - Added reference to validation knowledge base ("Проверяй форматы полей по справочнику выше")
  - Expanded comment trigger to include "несоответствие длины" (length mismatches)
- Improved templates/article-proposal-triage.md:
  - Added mass mailings from media/orgs/PR agencies as negative criterion
  - Added multilingual note: same criteria regardless of email language
- Expanded knowledge/payment-data-validation.md:
  - Added missing fields: passport_date, passport_issued_by, bank_name (both Russian and global)
  - Clarified INN length by entity type: 12 digits for individuals, 10 for IP/legal entities
- Added refund handling section to knowledge/tech-support.md:
  - LLM cannot process refunds, should not promise them, should escalate

**Notes:**
- All changes are content-only (templates + knowledge files), no code changes
- All 274 tests pass
- Files reviewed but not changed (already good): translate-name.md, knowledge/support-triage.md, knowledge/email-inbox.md, knowledge/contractors.md

### Session 22 (2026-03-01) — Maintenance: Write Tests (round 4)
**Status:** Complete

**What was done:**
- Created 14 new test files with 229 tests (total: 503 tests across 23 files, all passing in 1.26s)

| File | Tests | Covers |
|---|---|---|
| `test_docs_gateway.py` | 26 | `format_date_ru()`, `format_date_en()`, `_find_placeholder_index()` |
| `test_email_parse.py` | 18 | `EmailGateway._parse()` — raw email → IncomingEmail |
| `test_prompt_loader.py` | 13 | `load_template()`, `load_knowledge()` |
| `test_compose_request.py` | 18 | compose functions structure, model registry, key extraction |
| `test_support_user_lookup.py` | 23 | `_fmt_account()`, `_fmt_subscriptions()`, `_fmt_payments()`, `_fmt_audit_log()` |
| `test_support_email_service.py` | 6 | `_format_thread()` |
| `test_flow_dsl.py` | 26 | `FlowState`, `Transition`, `Flow`, `AdminCommand`, `BotFlows` |
| `test_flow_engine.py` | 13 | `_build_states_group()`, `_resolve_transition()` |
| `test_flow_callbacks_helpers.py` | 7 | `_dup_button_label()` |
| `test_bot_helpers.py` | 12 | `prev_month()`, `current_month()`, `is_admin()` |
| `test_budget_repo.py` | 7 | `_sheet_name()`, `sheet_url()` |
| `test_rules_repo.py` | 6 | `RedirectRule`, `FlatRateRule`, `ArticleRateRule` |
| `test_flows_structure.py` | 28 | Flow state machine integrity, transitions, admin commands |
| `test_models_properties.py` | 26 | `display_name`, `all_names`, `type`, `currency`, `SHEET_COLUMNS` |

**Notes:**
- All tests are pure-logic, no mocking of gateways/APIs
- Coverage now extends to prompt loading, email parsing, flow DSL, flow engine, compose functions, support formatting, bot helpers, and model properties
- Remaining untested: service-layer orchestration code (requires full mocking of gateways)

### Session 23 (2026-03-02) — Plan 2 Phase 1.1-1.4: Email Decision Tracking (DB + Models + Wiring)
**Status:** Complete (Phase 1.1, 1.2, 1.3, 1.4 — all items)

**What was done:**
- Added `email_decisions` table to `_SCHEMA_SQL` in `db_gateway.py` (UUID PK, task, channel, input_message_ids TEXT[], output, status, decided_by, decided_at)
- Added 5 new methods to `DbGateway`:
  - `create_email_decision(task, channel, input_message_ids, output="") -> str`
  - `update_email_decision(decision_id, status, decided_by=None)`
  - `update_email_decision_output(decision_id, output)`
  - `get_email_decision(decision_id) -> dict | None`
  - `get_thread_message_ids(thread_id) -> list[str]`
- Modified `TechSupportHandler.discard(uid, draft=None)` to save rejected drafts to `email_messages` with `direction='draft_rejected'` when draft is provided
- Added `self._db = DbGateway()` to `InboxService.__init__()`
- Wired decision tracking into all InboxService flows:
  - `_handle_support()`: creates PENDING SUPPORT_ANSWER decision, sets `draft.decision_id`
  - `_handle_editorial()`: creates PENDING ARTICLE_APPROVAL decision, sets `item.decision_id`
  - `approve_support()`: updates decision output + status APPROVED
  - `skip_support()`: updates decision REJECTED, passes draft to discard for storage
  - `approve_editorial()`: updates decision APPROVED
  - `skip_editorial()`: updates decision REJECTED
- Added `decision_id: str = ""` to `SupportDraft` and `EditorialItem` in `common/models.py`
- All 503 tests pass

**Notes:**
- `InboxService` creates its own `DbGateway` instance (separate from `TechSupportHandler`'s) — schema init is idempotent via CREATE IF NOT EXISTS
- `input_message_ids` for decisions uses `[email.message_id]` — the single inbound email that triggered the decision
- Decision output is set at approval time (captures any admin edits via `update_and_approve_support`)
- Rejected drafts saved with `direction='draft_rejected'` and `message_id=<draft-rejected-{uuid}>` prefix

### Session 24 (2026-03-02) — Plan 2 Phase 1.5: Tests for Email Decision Tracking
**Status:** Complete (all 7 items)

**What was done:**
- Extended `tests/test_db_gateway.py` with 9 new tests:
  - `_make_gw()` helper creates DbGateway with properly mocked psycopg2 connection/cursor
  - `TestEmailDecisionsCRUD` (7 tests): create, update, update_output, get (found + not found), default values
  - `TestGetThreadMessageIds` (2 tests): returns list of message_ids, empty thread
- Created `tests/test_inbox_service.py` with 14 new tests:
  - `_make_service()` helper patches all 4 InboxService dependencies (TechSupportHandler, GeminiGateway, EmailGateway, DbGateway)
  - `TestApproveSupportDecision` (4 tests): updates decision APPROVED, skips DB when no decision_id, sends email, handles nonexistent uid
  - `TestSkipSupportDecision` (4 tests): updates decision REJECTED, calls discard with draft, skips DB when no decision_id, discards even for unknown uid
  - `TestApproveEditorialDecision` (3 tests): updates decision APPROVED, skips DB when no decision_id, handles nonexistent uid
  - `TestSkipEditorialDecision` (3 tests): updates decision REJECTED, skips DB when no decision_id, no DB call for unknown uid

**Net result:** 23 new tests (526 total), all passing in ~11s

**Notes:**
- Phase 1 is now fully complete (1.1-1.5 all checked off)
- These are the first service-layer tests with mocked dependencies — established `_make_service()` pattern for future InboxService testing
- `_make_gw()` pattern useful for testing any future DbGateway methods

### Session 24b (2026-03-02) — Plan 2 Phase 2.1: /health command
**Status:** Complete (all 10 items)

**What was done:**
- Added `HEALTHCHECK_DOMAINS` (list from comma-separated env var, default `republicmag.io,redefine.media`) and `KUBECTL_ENABLED` (bool, default False) to `common/config.py`
- Created `backend/domain/healthcheck.py`:
  - `HealthResult` dataclass (name, status, details)
  - `run_healthchecks()` — HTTP GET against each domain (timeout 5s), optional kubectl pod checks
  - `_kubectl_checks()` — parses `kubectl get pods --no-headers` output, checks Running status + readiness
  - `format_healthcheck_results()` — checkmark/cross icons per result, or "No checks configured" fallback
- Added `cmd_health` handler in `flow_callbacks.py` — typing indicator + `asyncio.to_thread(run_healthchecks)` + formatted reply
- Registered `/health` as AdminCommand in `flows.py` (description: "Проверка доступности сайтов и подов")
- Re-exported `run_healthchecks` and `format_healthcheck_results` from `backend/__init__.py`

**Notes:**
- `run_healthchecks()` is sync (uses requests + subprocess), wrapped in `asyncio.to_thread()` in the handler
- HTTP status < 400 = ok, >= 400 = error
- kubectl readiness check: `ready.split("/")[0] == ready.split("/")[1]` (e.g. "1/1" is ok, "0/1" is error)
- All 526 tests pass

### Session 25 (2026-03-02) — Plan 2 Phase 2.2 + 2.4: /tech_support command + remove code context from email pipeline
**Status:** Complete (all items in 2.2 and 2.4)

**What was done:**
- Created `templates/tech-support-question.md` — Russian-language prompt template with KNOWLEDGE, QUESTION, CODE_CONTEXT, VERBOSE placeholders. Instructs JSON output `{"answer": "..."}` for GeminiGateway compatibility.
- Added `tech_support_question()` compose function to `compose_request.py`:
  - Loads `base.md` + `tech-support.md` knowledge with SUBSCRIPTION_SERVICE_URL replacement
  - Verbose text: "Можешь дать развёрнутый ответ." vs "Отвечай кратко, 1-3 абзаца."
  - Added `"tech_support_question"` to `_MODELS` dict
- Added `_answer_tech_question(question, verbose)` sync helper in `flow_callbacks.py`:
  - Creates GeminiGateway instance
  - Optionally fetches code context: calls `tech_search_terms()` to determine if code search needed, then greps repos and extracts snippets (same pattern as `TechSupportHandler._fetch_code_context`)
  - Calls `tech_support_question()` compose function, then Gemini
  - Returns answer string
- Added `cmd_tech_support(message, state)` async handler:
  - Parses question text and `-v`/`verbose` flag
  - Shows TYPING indicator, calls helper via `asyncio.to_thread`
  - Truncates to 4000 chars, handles errors
- Registered `/tech_support` as AdminCommand in `flows.py` (description: "Задать вопрос по техподдержке")
- **Phase 2.4**: Removed `code_context = self._fetch_code_context(email_text)` from `TechSupportHandler.draft_reply()`. Kept `_fetch_code_context()` method and RepoGateway intact (pattern reused by `/tech_support`).
- Updated `test_compose_request.py` to include new `tech_support_question` model key

**Notes:**
- New imports added to `flow_callbacks.py`: `compose_request`, `GeminiGateway`, `RepoGateway` (all at top level)
- `/tech_support` code context fetch is wrapped in try/except — silently continues without code if repos aren't available
- All 526 tests pass

### Session 26 (2026-03-02) — Plan 2 Phase 2.3 + 2.5: /code command + Phase 2 tests
**Status:** Complete (all Phase 2 items done)

**What was done:**
- Created `backend/domain/code_runner.py`:
  - `run_claude_code(prompt, verbose=False) -> str` — runs Claude CLI as subprocess
  - `subprocess.run(["claude", "-p", prompt, "--max-turns", "5"], cwd=REPOS_DIR, timeout=300)`
  - When not verbose, prepends `_CONCISE_PREFIX` (Russian instruction for Telegram-friendly output)
  - Truncates output to 4000 chars
  - Handles TimeoutExpired, FileNotFoundError, generic exceptions — returns error strings, never raises
- Added `cmd_code` handler in `flow_callbacks.py` (same pattern as `cmd_tech_support`)
- Registered `/code` as AdminCommand in `flows.py`
- Updated `Dockerfile`: added Node.js 20 + `@anthropic-ai/claude-code` installation
- Re-exported `run_claude_code` from `backend/__init__.py`

**Phase 2.5 Tests:**
- Created `tests/test_healthcheck.py` — 15 tests (HTTP up/down/exception, multiple domains, kubectl running/error/disabled, format output)
- Created `tests/test_code_runner.py` — 9 tests (success, verbose flag, concise prefix, truncation, stderr fallback, empty output, timeout, file not found, exception)
- Extended `tests/test_compose_request.py` — 4 tests for `tech_support_question` (tuple structure, question in prompt, verbose text, code context)
- Extended `tests/test_tech_support_handler.py` — 1 test confirming `_fetch_code_context` is NOT called from `draft_reply()`

**Net result:** 29 new tests (555 total), all passing in ~1.3s

**Notes:**
- Phase 2 is now fully complete (2.1-2.5 all checked off)
- `/code` command imports `run_claude_code` directly in `flow_callbacks.py` (not through `backend/__init__`)
- Claude CLI needs `ANTHROPIC_API_KEY` in environment (already in config.py)
- Dockerfile now has a second `RUN` layer for Node.js/Claude CLI (~200MB addition)

### Session 27 (2026-03-02) — Plan 2 Phase 3.1-3.4: NL Bot + Groupchat Support
**Status:** Complete (Phase 3.1, 3.2, 3.3, 3.4 — all items)

**What was done:**

Phase 3.1 — Command classifier:
- Created `templates/classify-command.md` — Russian-language LLM prompt with `{{COMMANDS}}` and `{{TEXT}}` placeholders, returns JSON `{"command": "..." | null, "args": "..."}`
- Added `classify_command(text, commands_description)` to `compose_request.py` (returns prompt + model + response keys)
- Added `"classify_command": "gemini-2.5-flash"` to `_MODELS` dict
- Created `backend/domain/command_classifier.py`:
  - `ClassifiedCommand` dataclass (`command: str`, `args: str`)
  - `CommandClassifier` class with `classify(text, available_commands) -> ClassifiedCommand | None`
  - Formats commands dict into markdown list, calls compose function + Gemini, validates result against available commands
- Re-exported `CommandClassifier` from `backend/__init__.py`

Phase 3.2 — Groupchat configuration:
- Added `GroupChatConfig` dataclass to `flow_dsl.py` (`chat_id`, `allowed_commands`, `natural_language=True`)
- Added `group_configs: list[GroupChatConfig]` field to `BotFlows`
- Added `EDITORIAL_CHAT_ID` (int, default 0) and `BOT_USERNAME` (str) to `common/config.py`
- Defined editorial groupchat config in `flows.py` with `allowed_commands=["health", "tech_support", "code"]`, filtered when `EDITORIAL_CHAT_ID` is 0
- Added new env vars to `config/example/.env`

Phase 3.3 — Group message handler:
- Added `_extract_bot_mention(text, bot_username) -> str | None` helper
- Added `_GROUP_COMMAND_HANDLERS` dict (health → cmd_health, tech_support → cmd_tech_support, code → cmd_code)
- Added `_COMMAND_DESCRIPTIONS` dict with Russian descriptions
- Added `_dispatch_group_command(command, args_text, message, state)` — temporarily sets `message.text` to `/{command} {args}` for handler compatibility
- Added `handle_group_message(message, state, group_config)`:
  - Explicit commands: parses command name (strips @bot suffix), checks allowed_commands, dispatches
  - Natural language: detects @mention or reply-to-bot, runs CommandClassifier via asyncio.to_thread(), dispatches classified command

Phase 3.4 — Flow engine wiring:
- Added group router registration at the TOP of `register_flows()` — before /start, /menu, admin commands, and flow routers
- Router filters on `F.chat.type.in_({"group", "supergroup"})` and `F.text`
- Handler looks up `GroupChatConfig` by `message.chat.id`, ignores unconfigured groups
- No changes to `main.py` needed

**Notes:**
- Group router is registered FIRST so it intercepts all text messages in configured groups before admin/private handlers
- Commands in groups don't require `is_admin()` — they just need to be in the group's `allowed_commands` list
- Unconfigured groups: handler returns without consuming message, so it falls through normally
- `_dispatch_group_command` temporarily modifies `message.text` for handler compatibility (restored in finally block)
- `handle_group_message` detects reply-to-bot via `message.reply_to_message.from_user.is_bot`
- All 555 tests pass
- Updated `test_compose_request.py` to include `classify_command` in expected model keys

### Session 28 (2026-03-02) — Plan 2 Phase 3.5: Tests for Phase 3
**Status:** Complete (all 6 items)

**What was done:**
- Created `tests/test_command_classifier.py` — 18 tests across 3 classes:
  - `TestClassifiedCommand` (2): dataclass field storage
  - `TestCommandClassifier` (11): Russian NL inputs → correct commands (health, tech_support, code), None for irrelevant/invalid/unknown commands, Gemini call verification, args handling
  - `TestClassifyCommandCompose` (5): compose function structure, model, keys, prompt content
- Extended `tests/test_flow_callbacks_helpers.py` — 21 new tests across 3 classes:
  - `TestExtractBotMention` (8): @username extraction with space/newline separators, no mention, wrong username, mention in middle, multiline
  - `TestGroupCommandHandlers` (5): handler dict contents, callability, expected commands
  - `TestCommandDescriptions` (4): description presence, non-empty strings, expected commands
- Extended `tests/test_flow_dsl.py` — 9 new tests across 2 classes:
  - `TestGroupChatConfig` (5): defaults, custom commands, NL override, chat_id filtering
  - `TestBotFlowsGroupConfigs` (2): default empty, stored configs retrievable
- Extended `tests/test_flow_engine.py` — 3 new tests:
  - `TestRegisterFlowsGroupConfig` (3): group router added when configs present, absent when empty, named "group"
- Extended `tests/test_flows_structure.py` — 1 new test: group_configs is a list

**Net result:** 46 new tests (601 total), all passing in 1.45s

**Notes:**
- Phase 3 is now fully complete (3.1-3.5 all checked off)
- CommandClassifier tests mock GeminiGateway.call() to return specific JSON responses
- `_extract_bot_mention` tested as pure function (no mocking needed)
- Flow engine group registration tests mock Dispatcher and verify router naming

### Session 28b (2026-03-02) — Plan 2 Phase 4.1-4.3: /articles + /lookup commands + tests
**Status:** Complete (all Phase 4 items done)

**What was done:**

Phase 4.1 — /articles command:
- Added `_ROLE_LABELS` and `_TYPE_LABELS` dicts in `flow_callbacks.py` — maps enums to Russian labels
- Created `cmd_articles` handler: parses `<name> [YYYY-MM]`, fuzzy-finds contractor, fetches articles via `asyncio.to_thread(fetch_articles)`, formats as display_name + role + month + count + article ID list
- Registered `/articles` as AdminCommand in `flows.py`

Phase 4.2 — /lookup command:
- Created `cmd_lookup` handler: parses `<name>`, fuzzy-finds contractor, shows display_name, type, role, mags, email, telegram status, invoice_number, bank data presence (without exposing sensitive fields)
- Registered `/lookup` as AdminCommand in `flows.py`

Both commands:
- Added to `_GROUP_COMMAND_HANDLERS` and `_COMMAND_DESCRIPTIONS` dicts
- Added to editorial groupchat's `allowed_commands` list
- Follow same fuzzy-find + suggestions pattern as `cmd_generate`

Phase 4.3 — Tests:
- Extended `tests/test_flow_callbacks_helpers.py` with 21 new tests across 5 classes:
  - `TestRoleLabels` (4): enum → label mappings
  - `TestTypeLabels` (4): enum → label mappings
  - `TestArticlesFormatting` (3): output format assembly
  - `TestLookupNoSensitiveData` (6): verifies passport, INN, bank_account, BIK, SWIFT, etc. are absent from output
  - `TestFuzzySuggestionFormatting` (4): suggestion list format

**Net result:** 622 total tests, all passing in 1.38s

**Notes:**
- Phase 4 is now fully complete (4.1-4.3 all checked off)
- Lookup uses same fuzzy_find threshold=0.4 as cmd_generate for suggestions
- Lookup shows bank data as "заполнены"/"не заполнены" — no raw bank details exposed
- Both commands are available in editorial groupchat

### Session 29 (2026-03-02) — Plan 2 Phase 5.1 + 5.2: LLM Classification Logging + Payment Validations
**Status:** Complete (all Phase 5.1 and 5.2 items)

**What was done:**

Phase 5.1 — `llm_classifications` table:
- Added `llm_classifications` table to `_SCHEMA_SQL` (UUID PK, task, model, input_text, output_json, latency_ms)
- Added `DbGateway.log_classification()` method
- Extended `GeminiGateway.call()` with optional `task` parameter:
  - When `task` is provided: measures latency via `time.time()`, logs to DB via `DbGateway().log_classification()`
  - DB logging wrapped in try/except — never blocks the LLM call
  - `DbGateway` imported lazily inside the `if task:` block to keep module decoupled
- Updated 6 callers with `task=` parameter:
  - `InboxService._llm_classify()` → `task="INBOX_CLASSIFY"`
  - `InboxService._handle_editorial()` → `task="EDITORIAL_ASSESS"`
  - `TechSupportHandler._fetch_user_data()` → `task="SUPPORT_TRIAGE"`
  - `TechSupportHandler._fetch_code_context()` → `task="TECH_SEARCH_TERMS"`
  - `CommandClassifier.classify()` → `task="COMMAND_CLASSIFY"`
  - `translate_name_to_russian()` in `backend/__init__.py` → `task="TRANSLATE_NAME"`

Phase 5.2 — `payment_validations` table:
- Added `payment_validations` table to `_SCHEMA_SQL` (UUID PK, contractor_id, contractor_type, input_text, parsed_json, validation_warnings TEXT[], is_final)
- Added `DbGateway.log_payment_validation()` — returns generated UUID
- Added `DbGateway.finalize_payment_validation()` — sets `is_final=TRUE`
- Wired into `_parse_with_llm()` in `flow_callbacks.py`:
  - After successful parse (no `parse_error`), logs via `DbGateway().log_payment_validation()`
  - Stashes validation ID in `result["_validation_id"]` for downstream use
  - Wrapped in try/except to never break user flow
- Wired into `_finish_registration()`:
  - Checks `collected.get("_validation_id")` and calls `finalize_payment_validation()`
  - Also wrapped in try/except

Tests:
- Extended `tests/test_db_gateway.py` with 6 new tests (log_classification, log_payment_validation, finalize)
- Created `tests/test_gemini_gateway.py` with 4 new tests (task logs to DB, no-task doesn't log, default model, DB failure doesn't raise)
- Total: 632 tests, all passing in 1.34s

**Notes:**
- `GeminiGateway` creates a new `DbGateway()` per logged call — lightweight since `DbGateway` auto-reconnects
- `_validation_id` key in result dict is ignored by downstream processing (unknown keys silently pass through)
- `parse_contractor_data()` is called from `backend/__init__.py`, not directly — the DB logging happens in the Telegram-side `_parse_with_llm` wrapper

### Session 30 (2026-03-02) — Plan 2 Phase 5.3 + 5.4: code_tasks table + rating + remaining tests
**Status:** Complete (all Phase 5 items done)

**What was done:**

Phase 5.3 — `code_tasks` table + rating:
- Added `code_tasks` table to `_SCHEMA_SQL` (UUID PK, requested_by, input_text, output_text, verbose, rating, rated_at)
- Added `DbGateway.create_code_task()` — INSERT with RETURNING id
- Added `DbGateway.rate_code_task()` — UPDATE rating + rated_at=NOW()
- Modified `cmd_code` handler: after Claude returns, saves task to DB (try/except), shows 1-5 rating inline keyboard
- Created `handle_code_rate_callback` — parses `code_rate:{task_id}:{rating}`, calls rate_code_task, removes keyboard
- Registered `handle_code_rate_callback` in `main.py` with `F.data.startswith("code_rate:")`

Phase 5.4 — Remaining tests:
- Added `TestCodeTasksCRUD` (3 tests) to `test_db_gateway.py`: create, create verbose, rate
- Added `TestHandleCodeRateCallback` (4 tests) to `test_flow_callbacks_helpers.py`: valid rating, invalid format (too few/many parts), DB error graceful degradation

**Net result:** 7 new tests (639 total), all passing in 1.35s

**Notes:**
- Phase 5 is now fully complete (5.1-5.4 all checked off)
- Plan 2 Phases 1-5 are all done. Phase 6 (domain refactor) is optional/stretch.
- DB logging in cmd_code is wrapped in try/except — never breaks user experience
- Rating buttons use compact single-row layout: "1" through "5"
- Callback data format: `code_rate:{uuid}:{1-5}` — fits within Telegram's 64-byte limit

### Session 31 (2026-03-02) — Maintenance: Spot Bugs (Plan 2 review)
**Status:** Complete

**What was done:**
- Thorough code review across all 15 files modified during Plan 2 (phases 1-5)
- Found and fixed 6 issues in `telegram_bot/flow_callbacks.py`:

1. **CONFIRMED BUG — `skip_editorial` called synchronously** (line ~1791):
   - `_inbox.skip_editorial(uid)` called without `await asyncio.to_thread()`, blocking the event loop during DB write
   - **Fix**: Wrapped in `await asyncio.to_thread(_inbox.skip_editorial, uid)`

2. **CONFIRMED BUG — `rate_code_task` called synchronously** (line ~1806):
   - `DbGateway().rate_code_task(...)` in `handle_code_rate_callback` blocked the event loop
   - **Fix**: Wrapped in `await asyncio.to_thread(DbGateway().rate_code_task, task_id, int(rating))`

3. **CONFIRMED BUG — `create_code_task` called synchronously** (line ~605):
   - DB insert in `cmd_code` handler blocked the event loop
   - **Fix**: Wrapped in `await asyncio.to_thread(DbGateway().create_code_task, ...)`

4. **CONFIRMED BUG — `finalize_payment_validation` called synchronously** (line ~1439):
   - DB update in `_finish_registration` blocked the event loop
   - **Fix**: Wrapped in `await asyncio.to_thread(DbGateway().finalize_payment_validation, validation_id)`

5. **CONFIRMED BUG — `log_payment_validation` called synchronously** (line ~1598):
   - DB insert in `_parse_with_llm` blocked the event loop
   - **Fix**: Wrapped in `await asyncio.to_thread(DbGateway().log_payment_validation, ...)`

6. **OVERSIGHT — Missing `task` parameter in `_answer_tech_question`** (line ~525):
   - `gemini.call(prompt, model)` for tech search terms lacked `task="TECH_SEARCH_TERMS"` — call worked but wasn't logged to `llm_classifications` table
   - **Fix**: Added `task="TECH_SEARCH_TERMS"` to match `tech_support_handler.py`

**Non-bug observations (not fixed):**
- `gemini_gateway.py` creates new `DbGateway()` per classification log — wasteful but not a correctness bug
- `is_reply_to_bot` checks `is_bot` on any bot, not specifically this bot — unlikely issue in practice
- Group configs list comprehension pattern is valid Python, just unusual

**Notes:**
- All 639 tests pass after fixes
- The common pattern was: Plan 2 DB logging code was added to async handlers but called synchronously, unlike existing DB calls which were properly wrapped in `asyncio.to_thread()`

### Session 32 (2026-03-02) — Maintenance: Write Tests (Plan 2 handlers)
**Status:** Complete

**What was done:**
- Created `tests/test_plan2_handlers.py` — 68 tests across 11 classes covering Plan 2 handler and service-layer code with mocked dependencies:
  - `TestHandleGroupMessageExplicitCommands` (5): explicit command dispatch, @bot suffix stripping, allowed_commands filtering
  - `TestHandleGroupMessageNaturalLanguage` (8): @mention triggers classifier, NL disabled ignores mentions, classification errors silenced, reply-to-bot detection
  - `TestCmdHealth` (2): healthcheck dispatch and reply
  - `TestCmdTechSupport` (8): question parsing, verbose flags, truncation, error handling
  - `TestAnswerTechQuestion` (7): two-step Gemini flow (search terms + answer), code context integration, repo failure graceful degradation, 5-file limit
  - `TestCmdCode` (10): run + DB save + rating keyboard, verbose flags, DB failure graceful, error messages
  - `TestCmdArticles` (6): contractor lookup, month param, fuzzy suggestions, no-articles message
  - `TestCmdLookup` (9): full output format, sensitive data exclusion, telegram/bank status, fuzzy suggestions
  - `TestParseWithLlm` (8): validation logging to DB, parse_error skip, DB failure graceful, contractor_type mapping
  - `TestDispatchGroupCommand` (4): text rewriting for handler compatibility, text restoration in finally block
  - Plus a few inline helper tests

**Net result:** 68 new tests (707 total), all passing in 1.48s

**Notes:**
- First comprehensive handler-level test coverage for Plan 2 commands
- Uses `unittest.mock.patch` for all external deps (Gemini, DB, Telegram, RepoGateway)
- `AsyncMock` for async Telegram message methods, `MagicMock` for sync gateways
- Tests verify both success paths and error/edge cases
- `_parse_with_llm` tests validate the payment validation logging integration

### Session 33 (2026-03-02) — Maintenance: Write Tests (round 5 — service-layer integration)
**Status:** Complete

**What was done:**
- Evaluated Phase 6 (LLM domain structure refactor): deferred as premature abstraction that conflicts with project's minimalism philosophy. Noted in plan.
- Added 32 new service-layer integration tests with mocked dependencies across 3 files:

**`tests/test_inbox_service.py`** — 11 new tests across 4 classes:
  - `TestInboxServiceProcess` (3): process() routing to support/editorial/ignore
  - `TestInboxServiceClassify` (3): direct address match vs LLM fallback
  - `TestHandleSupport` (2): SupportDraft creation with decision_id, duplicate UID handling
  - `TestHandleEditorial` (3): editorial assessment routing, forward=false, no chief editor guard
  - Consolidated `_make_service` and `_make_service_full` helpers into one

**`tests/test_tech_support_handler.py`** — 12 new tests across 4 classes:
  - `TestDraftReply` (3): full flow (thread→triage→user data→LLM→SupportDraft), thread history, can_answer=false
  - `TestSaveOutbound` (2): outbound message saving with field mapping, no-op for unknown UID
  - `TestDiscard` (3): rejected draft saving, cleanup without draft, no-op for unknown UID
  - `TestFetchUserData` (4): LLM triage→user lookup, fallback email, empty needs, exception handling

**`tests/test_support_user_lookup.py`** — 9 new tests in 1 class:
  - `TestFetchAndFormat` (9): per-need section fetching (subscriptions, payments, account, audit_log, redefine), multiple needs, empty needs, gateway exceptions, fallback redefine_user_id

**Net result:** 32 new tests (739 total), all passing in 1.52s

**Notes:**
- Review agent cleaned up unused imports (MagicMock, ANY, pytest, PendingItem) and removed 1 redundant test
- First comprehensive end-to-end tests for InboxService.process(), TechSupportHandler.draft_reply(), and SupportUserLookup.fetch_and_format()
- These tests mock all 4+ dependencies per service and verify return values, not just mock calls
- `_test_ternary.py` stray empty file in project root — needs manual deletion (rm blocked by security policy)

### Session 34 (2026-03-02) — Maintenance: Refactor (round 4)
**Status:** Complete

**What was done:**
- Refactoring pass across Plan 2 code, net -109 lines (104 added, 213 removed)
- Extracted 3 helpers in `flow_callbacks.py`:
  - `_safe_edit_text()` — replaces 8 duplicated try/except TelegramBadRequest blocks
  - `_parse_verbose_flag()` — shared verbose/`-v` parsing for `cmd_tech_support` and `cmd_code`
  - `_find_contractor_or_suggest()` — shared contractor lookup+fuzzy suggestions for `cmd_generate`, `cmd_articles`, `cmd_lookup`
- Removed 2 redundant inline `DbGateway` imports in `flow_callbacks.py` (already imported at top level)
- Removed dead `_fetch_code_context()` method (38 lines) from `tech_support_handler.py` — was no longer called after Plan 2 removed its invocation from `draft_reply()`
- Removed `self._repo_gw` instance storage from `TechSupportHandler.__init__()` (only `ensure_repos()` needed, called directly)
- Added `fetch_snippets()` method to `RepoGateway` — extracted snippet-building logic that was duplicated between `_answer_tech_question` in `flow_callbacks.py` and the now-removed `_fetch_code_context`
- Updated test mock paths in `test_flow_callbacks_helpers.py` and `test_plan2_handlers.py` to match import changes
- Removed 1 test (`TestDraftReplyNoCodeContext`) that tested the removed dead code

**Net result:** 738 tests pass (1 test removed with dead code), -109 lines

**Notes:**
- `RepoGateway.fetch_snippets()` is the natural home for snippet logic — operates on repo data via `search_code()` and `read_file()`
- `_find_contractor_or_suggest()` is async because `get_contractors()` is async
- All refactors preserve existing public behavior and function signatures

### Session 35 (2026-03-02) — Maintenance: Polish UX (bot reply texts)
**Status:** Complete

**What was done:**
- Reviewed all user-facing Telegram bot text for typos, grammar, inconsistency, and UX issues
- Fixed 5 grammar/punctuation issues in `replies.py`:
  - `wrong_code`: added trailing period
  - `invoice_ready`: fixed grammatical gender ("готова" → "готов" for masculine "счёт-оферта"), capitalized "Легиум"
  - `add_prompt`: removed stray space before `\n`, replaced colon with period
  - `amount_prompt`/`amount_invalid`: replaced formal "иную" with natural "другую", added guillemets around «ок»
  - `no_changes`: improved from "Изменений не найдено" to actionable "Не удалось распознать изменения. Попробуйте ещё раз или отправьте «отмена»."
- Centralized 10 hardcoded Russian strings from `flow_callbacks.py` to `replies.py`:
  - `admin.articles_usage`, `admin.lookup_usage`, `admin.tech_support_usage`, `admin.tech_support_no_question`, `admin.tech_support_error`, `admin.code_usage`, `admin.code_no_query`, `admin.code_error`, `admin.orphans_none`, `admin.orphans_found`
- Stopped exposing raw Python exceptions to users in `cmd_tech_support` and `cmd_code` — now show friendly error messages
- Added missing TYPING chat action in `handle_manage_redirects` (was loading sheet data without feedback)
- Updated 2 test assertions in `test_plan2_handlers.py` to match new error text

**Net result:** 738 tests pass, +11 lines net

**Notes:**
- Remaining hardcoded strings in `flow_callbacks.py` are mostly dynamic format strings that are hard to template (contractor-specific output). Not worth centralizing.
- `_test_ternary.py` stray file still needs manual deletion (rm blocked by security policy)

### Session 36 (2026-03-02) — Maintenance: Write Tests (round 6 — invoice generation)
**Status:** Complete

**What was done:**
- Created 3 new test files covering the invoice generation pipeline with mocked gateways:

**`tests/test_generate_invoice.py`** — 9 classes, 21 tests:
  - `TestGenerateGlobalInvoice` (5): template selection (regular/photo), replacement keys, articles table with English headers
  - `TestGenerateIPInvoice` (5): invoice number increment, template selection, RUB-specific replacements (OGRNIP, passport), Russian headers
  - `TestGenerateSamozanyatyInvoice` (4): invoice number increment, template selection, INN/address replacements
  - `TestDebugMode` (3): skips increment+save, still generates PDF, Global never increments
  - `TestDriveUploadFailure` (1): gdrive_path="" on error, PDF still returned
  - `TestInvoiceDateDefault` (1): defaults to date.today()
  - `TestArticleIdsInInvoice` (2): populated IDs, empty articles
  - `TestInvoiceStatus` (1): always DRAFT

**`tests/test_generate_batch_invoices.py`** — 6 classes, 14 tests:
  - `TestBatchFiltering` (5): already-generated, no budget, zero amount, EUR/RUB currency selection, empty budget raises
  - `TestBatchSuccess` (3): counts by type, empty list, tuple structure
  - `TestBatchErrors` (2): article fetch error, generation error — both logged and continue
  - `TestBatchProgress` (3): callback per contractor, callback on error, None callback ok
  - `TestBatchDebugMode` (1): debug flag passthrough

**`tests/test_prepare_invoice.py`** — 1 class, 6 tests:
  - Found with doc_id, not found, no doc_id, PDF export fails, correct ID matching, first-match on duplicates

**Net result:** 41 new tests (780 total), all passing in 1.57s

**Notes:**
- Uses `__new__` pattern to construct instances with mocked gateways (bypassing __init__)
- Factory helpers (_global, _samoz, _ip, _invoice) match existing patterns in test_compute_budget.py
- These were the last high-value untested pure-domain modules
- Invoice generation is now comprehensively tested: single, batch, and re-export

### Session 37 (2026-03-02) — Maintenance: Spot Bugs (round 5)
**Status:** Complete

**What was done:**
- Thorough code review of all Plan 2 files (flow_callbacks.py, gemini_gateway.py, db_gateway.py, etc.)
- Found and fixed 3 confirmed bugs:

1. **DB Connection Leak from throw-away `DbGateway()` instances**:
   - 5 call sites in `flow_callbacks.py` and 1 in `gemini_gateway.py` created new `DbGateway()` per call
   - Each instance opens a Postgres connection that was never closed → connection exhaustion over time
   - **Fix**: Created module-level `_db = DbGateway()` in `flow_callbacks.py`, reuse single instance. In `gemini_gateway.py`, added lazily-initialized `self._db` attribute.

2. **`_validation_id` leaking into Google Sheets writes** (`handle_update_data`):
   - Internal UUID tracking key passed through `parsed_updates` filter → written to Google Sheet as if it were contractor data
   - **Fix**: Added `not k.startswith("_")` filter to `parsed_updates` comprehension

3. **`_validation_id` leaking into LLM context and admin notifications**:
   - In `_parse_with_llm`: UUID included in `filled` dict sent to LLM as "already collected" context
   - In `_forward_to_admins`: UUID shown to admin in registration notification
   - **Fix**: Filter `_`-prefixed keys from `filled` context dict and admin notification formatting; pop `_validation_id` from `parsed` in `handle_data_input` and re-add to `collected` separately

- Removed stray `_test_ternary.py` file from git tracking (rm blocked, but git clean will handle)
- Updated test mocks to match module-level `_db` pattern

**Notes:**
- All 780 tests pass
- The DB connection leak was potentially the most impactful — could exhaust Postgres connections during batch invoice operations
- `_validation_id` leak was a PII-adjacent issue (internal UUIDs exposed to admin users)

## Next up

- Plan 2 is complete through Phase 5. Phase 6 deferred (see plan notes).
- Continue maintenance mode: refactor, improve prompts, or polish UX.
- Test coverage is now strong across all layers. Remaining untested: low-value thin wrappers (gateways to external APIs).
- `_test_ternary.py` stray empty file in project root — needs manual deletion (rm blocked by security policy)
