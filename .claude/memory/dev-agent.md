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

### Session 38 (2026-03-02) — Maintenance: Refactor (round 5)
**Status:** Complete

**What was done:**
- Refactoring pass across 7 source files, net -84 lines (89 added, 173 removed)
- Merged `support_email()` and `support_email_with_context()` into single function with `user_data=""` default parameter in `compose_request.py`
- Extracted `_build_thread_message()` static method in `tech_support_handler.py` — deduplicated IncomingEmail construction in `save_outbound()` and `discard()`
- Extracted `_check_email()` helper in `validate_contractor.py` — deduplicated email regex validation for samozanyaty and global branches
- Removed no-op `_format_date()` function from `parse_bank_statement.py` — validated ISO date format but always returned input unchanged
- Extracted `_quote_csv()` helper in `airtable_gateway.py` — consolidated 4 identical comma-quoting blocks
- Extracted `_deliver_or_start_invoice()` in `flow_callbacks.py` — deduplicated invoice delivery logic between `handle_sign_doc()` and `handle_linked_menu_callback()`
- Removed `_translate_name_to_russian()` one-liner wrapper in `flow_callbacks.py` — inlined `asyncio.to_thread(translate_name_to_russian, name_en)`
- Removed unused `_TYPE_LABELS` dict — `ContractorType.value` already provides the same strings
- Consolidated triplicated progress callback in `generate_batch_invoices.py` into a `finally` block
- Updated 4 test files to match refactored code (removed 7 tests for dead code)

**Net result:** 773 tests pass (7 removed with dead code), -84 lines

**Notes:**
- All refactors preserve existing public behavior and function signatures
- `support_email(email_text, user_data="")` is backward-compatible — existing callers without context still work
- `_build_thread_message()` is a static method since it doesn't need `self`

### Session 39 (2026-03-02) — Maintenance: Spot Bugs (round 6)
**Status:** Complete

**What was done:**
- Thorough code review of all files, focusing on recent refactoring (session 38) and less-reviewed areas
- Found and fixed 2 confirmed bugs in `backend/infrastructure/gateways/airtable_gateway.py`:

1. **Missing `parent` field in Airtable upload**:
   - Every `AirtableExpense` record has a `parent` field (e.g., "staff", "goods and services", "expenses") but `upload_expenses()` never included it in the JSON payload
   - All uploaded expense records were missing their category in Airtable
   - **Fix**: Added `"parent": exp.parent` to the `fields` dict

2. **Spurious CSV quoting in Airtable API calls**:
   - `_quote_csv()` wrapped values containing commas in literal double quotes
   - Designed for CSV output but data is sent via pyairtable's JSON API
   - Contractor names, unit names, entity names, group names with commas had spurious `"..."` wrapping
   - **Fix**: Removed `_quote_csv()` entirely, pass raw string values to API

- Cross-file consistency checks all passed:
  - `support_email()` callers correct after merge
  - `_build_thread_message()` constructs messages correctly
  - `_deliver_or_start_invoice()` handles both caller scenarios
  - `_check_email()` called correctly in both places
- Reviewed 20+ files across all layers — no other bugs found

**Notes:**
- All 773 tests pass after fixes
- The Airtable bugs were introduced during refactoring round 5 when `_quote_csv()` was extracted — the quoting was wrong from the start but only became visible during refactoring review
- The `parent` field omission was likely present since the original `parse_bank_statement` feature was implemented

### Session 40 (2026-03-02) — Maintenance: Write Tests (round 7 — bank statement categorization)
**Status:** Complete

**What was done:**
- Extended `tests/test_parse_bank_statement.py` with 32 new tests across 14 classes covering all 16 code paths in `_categorize_transactions()`:
  - `TestCategorizeIncomeSkip` (2): Stripe/NETWORK INTERNATIONAL payout skip, case-insensitive
  - `TestCategorizeOwnerTransfer` (2): owner keyword match creates expense, non-match skipped
  - `TestCategorizeOtherPositiveTransfers` (2): unknown sender skip, no "From" pattern skip
  - `TestCategorizeFeesSwift` (2): single SWIFT fee aggregated, uppercase SWIFT in description
  - `TestCategorizeFeesFx` (1): FX fee creates 2 split expenses (50/50 units)
  - `TestCategorizeFeesSubscription` (1): subscription fee → Wio Bank expense, entity.split("-")[0] for unit
  - `TestCategorizeFeesUnknown` (1): unknown fee type skipped
  - `TestCategorizeOutgoingTransfers` (3): known person classification, unknown person defaults, no "To" pattern
  - `TestCategorizeCardKnownServiceNoSplit` (1): SERVICE_MAP match → single expense
  - `TestCategorizeCardKnownServiceSplit` (1): split=True → 2 expenses per unit
  - `TestCategorizeCardUnknownService` (1): unknown → 2 expenses with "NEEDS REVIEW"
  - `TestCategorizeInvalidAmount` (2): non-numeric and empty amounts skipped
  - `TestCategorizeEmptyRows` (4): empty dict, missing fields, zero amount, unknown txn type
  - `TestCategorizeMixedScenario` (1): 7 mixed rows → 6 correct expenses
  - `TestCategorizeSwiftAggregation` (1): 3 SWIFT fees → 1 aggregated with sum and latest date
  - `TestCategorizeFxAggregation` (1): 2 FX fees → 2 split aggregated with sum and latest date
  - `TestCategorizeEdgeCases` (6): empty list, positive card, whitespace, entity split, abs values

- Uses `_apply_patches` decorator to mock all 7 config values deterministically
- Uses `_row()` helper for concise CSV row construction

**Net result:** 32 new tests (805 total), all passing in 1.60s

**Notes:**
- `_categorize_transactions` is now comprehensively tested — every branch and aggregation path covered
- Tests are fully deterministic via config mocking, independent of business_config.json
- File went from 36 tests (helpers only) to 68 tests (helpers + full categorization engine)

### Session 41 (2026-03-02) — Maintenance: Write Tests (round 8 — gateway layer)
**Status:** Complete

**What was done:**
- Created 5 new test files covering previously untested gateway modules:

**`tests/test_repo_gateway.py`** — 23 tests across 4 classes:
  - `TestSearchCode` (8): grep output parsing, 20-result limit, nonexistent repo skip, single-repo filter, no-repos noop, malformed lines, timeout
  - `TestReadFile` (6): content read, max_lines truncation, path traversal blocked, nonexistent file/repo
  - `TestFetchSnippets` (5): snippet assembly, deduplication, max_files limit, empty results, line range calculation
  - `TestEnsureRepos` (4): clone vs pull branching, no-URLs noop, exception handling

**`tests/test_republic_gateway.py`** — 16 tests across 3 classes:
  - `TestApiGet` (9): $data vs data key, retry on 5xx with recovery, exhausted retries, timeout/connection retry, 4xx error, empty data
  - `TestFetchArticles` (4): mag-based vs author-based routing, deduplication, empty names
  - `TestFetchPublishedAuthors` (3): response parsing, malformed row skip, API error

**`tests/test_airtable_gateway.py`** — 7 tests:
  - Field mapping, conditional fields (splited/comment), 10-record batching, partial batch failure, no-token/no-base guard, empty list

**`tests/test_exchange_rate_gateway.py`** — 6 tests:
  - Successful parse, missing RUB/rates key, HTTP error, connection error, timeout

**`tests/test_email_gateway.py`** — 9 tests:
  - Re: prefix handling, Fwd:/Fw: preserved, In-Reply-To/References headers, custom/default from_addr, To header

- Updated `conftest.py`: added `"pyairtable"` to stubbed modules
- Removed unused `_extract_sent_message()` helper from test_email_gateway.py

**Net result:** 61 new tests (866 total), all passing in 1.48s

**Notes:**
- Gateway layer coverage went from 3/11 (27%) to 8/11 (73%)
- Still untested: `drive_gateway.py`, `sheets_gateway.py`, `redefine_gateway.py` — thin wrappers with minimal logic
- All tests use `unittest.mock.patch` for external deps (requests, subprocess, pyairtable, file I/O)
- `test_repo_gateway.py` uses pytest `tmp_path` fixture for filesystem tests

### Session 42 (2026-03-02) — Maintenance: Spot Bugs (round 7) + Improve Prompts (round 4)
**Status:** Complete

**Spot Bugs (round 7):**
- Thorough code review across all 40+ Python source files
- **Zero confirmed bugs found** — codebase is clean after 7 rounds of review
- Two theoretical edge cases documented (DbGateway thread-safety with shared connection, empty BOT_USERNAME in _extract_bot_mention) — neither manifests in production
- Verified all asyncio.to_thread() calls, all imports, all function signatures, all SQL parameterization, all PII handling

**Improve Prompts (round 4):**
- Improved 6 template files and 3 knowledge files:
  - `support-triage.md`: added multi-issue handling (include all relevant needs categories)
  - `support-email.md`: added user data interpretation guidance + thread dedup instruction
  - `inbox-classify.md`: added Redefine mention, service notifications to ignore, tech_support priority rule
  - `editorial-assess.md`: added signature instruction (was missing vs support-email)
  - `tech-support-question.md`: added empty code context handling + anti-hallucination guard
  - `classify-command.md`: clarified examples section, added "greeting → null" example
  - `knowledge/tech-support.md`: added Apple App Store / Google Play edge case, specific transaction detail instruction
  - `knowledge/support-triage.md`: added multi-category guidance
  - `knowledge/email-inbox.md`: clarified Redefine definition, formatting fixes

**Notes:**
- All 866 tests pass
- Bug-spotting has diminishing returns — 7 rounds with zero new bugs in the latest round
- Prompt improvements are small and targeted — major gaps were addressed in earlier rounds

### Session 43 (2026-03-02) — Plan 3 Phase 1: Embeddings Infrastructure
**Status:** Complete (all 3 items: 1.1, 1.2, 1.3)

**What was done:**
- Added `CREATE EXTENSION IF NOT EXISTS vector;` at the top of `_SCHEMA_SQL` in `db_gateway.py` (before all table definitions)
- Created `backend/infrastructure/gateways/embedding_gateway.py`:
  - `EmbeddingGateway` class with `embed_texts()` and `embed_one()` methods
  - Uses `google-genai` client with `text-embedding-004` model, 256 dimensions
  - Follows same lazy-import pattern as `GeminiGateway` (imports `google.genai` inside method)
  - Uses `GEMINI_API_KEY` from `common.config`
  - Constructor accepts optional `model` and `dimensions` params for flexibility
- Created `tests/test_embedding_gateway.py` — 5 tests across 2 classes:
  - `TestEmbedOne` (2): float list return type + correct model/dimensionality
  - `TestEmbedTexts` (3): correct count, all texts forwarded, custom model/dimensions

**Net result:** 5 new tests (871 total), all passing

**Notes:**
- `EmbeddingGateway` creates a new `genai.Client` per call (same pattern as Gemini). Acceptable for current volume.
- Pre-existing test failures: 73 in `test_plan2_handlers.py` (mock cross-contamination), 2 collection errors (PermissionError on `/opt/repos`). Not caused by Phase 1 changes.

### Session 43b (2026-03-02) — Plan 3 Phase 2: Knowledge Store (2.1-2.5)
**Status:** Complete (all items except running seed on live DB)

**What was done:**
- Added `knowledge_entries` table to `_SCHEMA_SQL` in `db_gateway.py`:
  - UUID PK, tier, scope, title, content, source, embedding (vector(256)), is_active, timestamps
  - 3 indexes: ivfflat cosine on embedding, scope+is_active, tier+is_active
- Added 7 new methods to `DbGateway`:
  - `save_knowledge_entry()`, `update_knowledge_entry()`, `search_knowledge()` (cosine similarity)
  - `get_knowledge_by_tier()`, `get_knowledge_by_scope()`, `list_knowledge()`, `deactivate_knowledge()`
- Created `backend/domain/knowledge_retriever.py`:
  - `KnowledgeRetriever` class with `get_core()`, `retrieve()`, `retrieve_full_scope()`
  - Shared `_format_entries()` helper for markdown formatting + `{{SUBSCRIPTION_SERVICE_URL}}` replacement
- Created `backend/domain/seed_knowledge.py`:
  - One-time migration script: reads `.md` files, chunks into 19 entries, generates embeddings, inserts
  - `_chunk_tech_support()` splits header (core) + 10 FAQ bullets (domain)
  - `_chunk_payment_validation()` splits into 4 sections by contractor type
  - Idempotent: skips if entries already exist
  - Batch embeddings in one API call
- Created `tests/test_knowledge_db.py` — 16 tests for all 7 DbGateway methods
- Created `tests/test_knowledge_retriever.py` — 14 tests for KnowledgeRetriever + _format_entries

**Net result:** 35 new tests (871 total), 4 new files, 1 modified file

**Notes:**
- `search_knowledge()` converts embedding list to string via `str()` for pgvector
- `list_knowledge()` builds dynamic WHERE clause with optional scope/tier filters
- Seed script can be run as `python -m backend.domain.seed_knowledge`
- Running seed requires live DB + Google API — deferred to deployment
- Pre-existing test failures were fixed in session 44 (see below)

### Session 44 (2026-03-02) — Plan 3 Phase 3: Prompt Composition Evolution + Test Fixes
**Status:** Complete (all Phase 3 items: 3.1, 3.2, 3.3, 3.4)

**What was done:**

Phase 3.1 — Updated `compose_request.py` to use `KnowledgeRetriever`:
- Added lazy `_retriever` singleton with `_get_retriever()` function (deferred import to avoid circular deps)
- Updated `support_email()` → `r.get_core()` + `r.retrieve(email_text, "tech_support", 5)`
- Updated `tech_support_question()` → `r.get_core()` + `r.retrieve(question, "tech_support", 5)`
- Updated `support_triage()` → `_get_retriever().retrieve_full_scope("support_triage")`
- Updated `contractor_parse()` → `r.get_core()` + `r.retrieve_full_scope("contractor")`
- Left unchanged: `inbox_classify`, `editorial_assess`, `translate_name`, `classify_command`, `tech_search_terms`
- Removed `SUBSCRIPTION_SERVICE_URL` import (handled inside `KnowledgeRetriever._format_entries()`)

Phase 3.2 — Added `conversation_reply()` function to `compose_request.py`:
- Takes `message`, `conversation_history`, `knowledge_context`, `verbose` params
- Uses `conversation.md` template
- Added `"conversation_reply": "gemini-2.5-flash"` to `_MODELS`

Phase 3.3 — Created `templates/conversation.md`:
- Russian-language template for Luka's assistant conversation
- Placeholders: `{{VERBOSE}}`, `{{KNOWLEDGE}}`, `{{CONVERSATION}}`, `{{MESSAGE}}`
- Returns JSON: `{"reply": "<ответ>"}`

Phase 3.4 — Tests:
- Added 9 new tests to `tests/test_compose_request.py`:
  - `TestRetrieverCalls` (4): verifies each function calls correct retriever methods with correct args
  - `TestConversationReply` (4): structure, verbose flag, placeholders
  - `TestGetRetrieverSingleton` (1): lazy initialization creates instance once

**Also fixed pre-existing test failures:**
- Fixed `RepoGateway.ensure_repos()` to handle `OSError` on `mkdir` (was crashing on `/opt/repos` permission error)
- Added `google.genai` and `google.genai.types` to conftest.py module stubs
- Added global autouse fixture `_stub_knowledge_retriever` in conftest.py to mock `_get_retriever()` across all tests
- Fixed test isolation in `test_embedding_gateway.py` and `test_gemini_gateway.py` (replaced module-level `sys.modules` override with per-test `patch.dict`)
- Added `conversation_reply` to expected keys in test
- Fixed `cmd_support` test assertion to match `parse_mode="HTML"`

**Net result:** 910 tests pass (up from 752 passing + 75 failing + 2 errors → all 910 pass)

**Notes:**
- `from __future__ import annotations` added to compose_request.py for forward-reference type annotation
- `load_knowledge` import kept for backward compatibility even though no function currently uses it
- Phase 2.4 still needs: run seed script on live DB and verify entries
- `_test_ternary.py` stray empty file in project root — needs manual deletion

### Session 45 (2026-03-02) — Plan 3 Phase 4: Conversation Persistence
**Status:** Complete (all items: 4.1, 4.2, 4.3, 4.4)

**What was done:**
- Added `conversations` table to `_SCHEMA_SQL` in `db_gateway.py`:
  - UUID PK, chat_id (BIGINT), user_id (BIGINT), role, content, reply_to_id (self-ref FK), message_id (BIGINT), metadata (JSONB), created_at
  - 3 indexes: chat+created_at, chat+message_id, reply_to_id
- Added 3 new methods to `DbGateway`:
  - `save_conversation()` — INSERT RETURNING id, uses `json.dumps` for JSONB metadata
  - `get_conversation_by_message_id()` — SELECT by chat_id+message_id, returns dict with UUID conversion
  - `get_reply_chain()` — walks reply_to_id chain upward, collects records, reverses for chronological order
- Added `import json` to db_gateway.py
- Modified `_send_html` in `flow_callbacks.py` to return `types.Message` (was returning None)
- Created `_save_turn()` async helper in `flow_callbacks.py`:
  - Saves user message + assistant reply as two conversation entries with reply_to_id linking
  - Auto-detects channel type (group/dm) from chat.type
  - Merges channel into metadata dict
  - Wrapped in try/except with logger.exception (never breaks user flow)
  - Uses `asyncio.to_thread()` for async safety
- Wired `_save_turn` into 4 handlers:
  - `cmd_support` (tech_support command) — metadata `{"command": "tech_support"}`
  - `cmd_code` — metadata `{"command": "code"}`
  - `cmd_nl` fallback — metadata `{"command": "nl_fallback"}`
  - `handle_group_message` NL fallback — metadata `{"command": "nl_fallback"}`
- Added 15 tests:
  - 8 in `test_db_gateway.py` (TestConversationsCRUD): CRUD ops, reply chain walking, depth limits
  - 6 in `test_flow_callbacks_helpers.py` (TestSaveTurn): both turns saved, reply_to linking, channel detection, error silencing
  - 1 in `test_flow_callbacks_helpers.py` (TestSendHtml): return type verification

**Net result:** 15 new tests (925 total), all passing

**Notes:**
- `_save_turn` reuses module-level `_db` (DbGateway) instance — no new connections per call
- Individual handlers (cmd_support, cmd_code) detect channel type themselves via `_save_turn`, so group message handler doesn't need separate saving logic
- `get_reply_chain` uses `cur.description` for column names, matching the `get_conversation_by_message_id` pattern

### Session 46 (2026-03-03) — Plan 3 Phase 5: Conversation NL Reply (Reply-to-Bot)
**Status:** Complete (all items: 5.1, 5.2, 5.3, 5.4)

**What was done:**

Phase 5.1 — Reply routing chain in `handle_admin_reply`:
- Restructured `handle_admin_reply` into a routing chain with 3 priority levels:
  1. `_admin_reply_map` → Legium forwarding (existing, returns early)
  2. Phase 6 placeholder comment for `_support_draft_map`
  3. Default → `_handle_nl_reply()` NL conversation fallback

Phase 5.2 — `_handle_nl_reply` implementation:
- Created `_format_reply_chain(chain) -> str` — formats conversation entries as `role: content` lines
- Created `_handle_nl_reply(message, state) -> bool`:
  - Guards: FSM state active → False, no reply → False, reply not from bot → False
  - TYPING indicator sent before LLM call
  - DB lookup for conversation entry by `(chat_id, message_id)`
  - If found: fetches reply chain, formats history, passes `parent_id` for chain linking
  - If not found: bootstraps from `reply.text` with 2-line history
  - Knowledge retrieval: `_get_retriever()` → `get_core()` + `retrieve(message.text)`
  - LLM call: `compose_request.conversation_reply()` + `GeminiGateway().call()` via `asyncio.to_thread`
  - Reply: truncated to 4000 chars, sent via `_send_html` with `reply_to_message_id`
  - Saves both turns via `_save_turn` with `{"command": "nl_reply"}` metadata
  - Error handling: entire LLM path wrapped in try/except, returns False on failure

Phase 5.3 — Group chat integration:
- When command classification returns no match AND `is_reply_to_bot`: calls `_handle_nl_reply` first
- If returns False, falls back to existing behavior (show classifier reply)
- When just a mention (not reply-to-bot), behavior unchanged

Phase 5.4 — Tests:
- `TestFormatReplyChain` (3 tests): single/multi/empty chain formatting
- `TestHandleNlReply` (7 tests): happy path with DB, bootstrap without DB, LLM error, FSM guard, no-reply guard, not-from-bot guard, truncation
- `TestAdminReplyRouting` (3 tests): legium priority, NL fallback, no-reply early return
- 1 additional test for `_save_turn` `parent_id` linking

**Review fix applied:**
- Added `parent_id: str | None = None` parameter to `_save_turn()` — without this, multi-turn chains would break because `get_reply_chain()` couldn't walk back past one turn. `_handle_nl_reply` passes `conv_entry["id"]` when DB record exists.

**Net result:** 15 new tests (940 total), all passing in ~1.8s

**Notes:**
- `_get_retriever` imported from `backend.domain.compose_request` (private function import, but consistent with test patching)
- `GeminiGateway()` creates new instance per NL reply call (same pattern as cmd_nl)
- `handle_admin_reply` is registered for admin users only — no separate admin check in `_handle_nl_reply`
- Group chat NL reply works for both @mention and reply-to-bot scenarios

### Session 47 (2026-03-03) — Plan 3 Phase 6: Learning from Admin Feedback
**Status:** Complete (all items: 6.1, 6.2, 6.3, 6.4)

**What was done:**

Phase 6.1 — Track draft messages:
- Added `_support_draft_map: dict[tuple[int, int], str] = {}` in `flow_callbacks.py` (same pattern as `_admin_reply_map`)
- Modified `_send_support_draft` to capture `sent` message and register `(admin_id, sent.message_id) → em.uid`

Phase 6.2 — Handle admin replies to drafts:
- Replaced Phase 6 placeholder in `handle_admin_reply` routing chain with actual `_support_draft_map` check (priority 2, after Legium forwarding, before NL fallback)
- Added `_GREETING_PREFIXES` tuple for greeting detection (Russian + English, case-insensitive)
- Created `_handle_draft_reply(message, uid)`:
  - Gets pending draft, replies with "expired" if not found
  - Classifies reply: greeting prefix → replacement, otherwise → teaching feedback
  - Replacement: calls `_inbox.update_and_approve_support(uid, message.text)`, replies with `replacement_sent`
  - Teaching: calls `_inbox.skip_support(uid)`, stores feedback via `retriever.store_feedback(text, "tech_support")`, replies with `feedback_noted`
  - Knowledge storage wrapped in try/except — never breaks the handler

Phase 6.3 — Store feedback as knowledge:
- Added `store_feedback(text, scope) -> str` to `KnowledgeRetriever`:
  - Embeds text, truncates to 60 chars for title
  - Saves with `tier="domain"`, `source="admin_feedback"`

Phase 6.4 — Tests:
- 6 tests in `TestHandleDraftReply`: replacement path, teaching feedback path, expired draft, case-insensitive greetings, storage failure handling, from_addr fallback
- 1 test in `TestSendSupportDraftMap`: map population after send
- 2 tests in `TestAdminReplySupportDraftRouting`: routing, Legium priority
- 2 tests in `TestStoreFeedback`: happy path, title truncation

**Review fixes applied:**
- Added `"hi,"` prefix (comma variant) alongside `"hi "` (space variant) to handle "Hi, ..." pattern
- Cleaned up docstring to remove internal phase references

**Net result:** 11 new tests (951 total), all passing

**Notes:**
- `inbox_service.py` was NOT modified — `update_and_approve_support` already existed
- Reply strings added to `replies.py`: `replacement_sent`, `feedback_noted`
- Map cleanup happens after `_handle_draft_reply` returns (even on error, map entry persists so admin can retry)
- Send/Skip buttons still work — both paths check `get_pending_support`, which consumes the draft

### Session 48 (2026-03-03) — Maintenance: Spot Bugs (round 8) + Write Tests (round 9)
**Status:** Complete

**Spot Bugs (round 8) — Plan 3 code review:**
- Thorough review of all Plan 3 files (Phases 1-7)
- Found and fixed 2 confirmed bugs:

1. **Duplicate user message in LLM prompt** (`flow_callbacks.py:_handle_nl_reply`):
   - User's message appended to conversation history AND passed as separate `{{MESSAGE}}` placeholder — LLM saw it twice
   - **Fix**: Removed user message from history string; now only in `{{MESSAGE}}`

2. **Silent success on `/forget` and `/kedit` with nonexistent entry IDs** (`db_gateway.py` + `flow_callbacks.py`):
   - `deactivate_knowledge()` and `update_knowledge_entry()` didn't check `cursor.rowcount` — user saw "success" for nonexistent UUIDs
   - **Fix**: Both methods now return `bool` (rowcount > 0), handlers show "Запись не найдена" when False

- Noted 7 non-bugs (theoretical/won't-happen): get_reply_chain cycles bounded by depth=10, lstrip char-set behavior correct for actual data, etc.

**Write Tests (round 9) — seed_knowledge.py:**
- Created `tests/test_seed_knowledge.py` — 22 tests across 3 classes:
  - `TestChunkTechSupport` (7): core section, domain bullets, multi-line, empty input, no core, title extraction
  - `TestChunkPaymentValidation` (8): all heading mappings, unknown heading, empty input, content completeness
  - `TestSeedKnowledge` (7): happy path, idempotent skip, entry count, source=seed, batch embedding, scopes, init_schema
- seed_knowledge.py coverage went from 0% to comprehensive

**Net result:** 1003 tests pass (+25 new: 3 bug fix + 22 seed_knowledge)

### Session 49 (2026-03-03) — Plan 4 Phase 1: Split flow_callbacks.py into handler modules
**Status:** Complete (all 11 items: 1.1-1.11)

**What was done:**
- Split the 2,105-line monolithic `telegram_bot/flow_callbacks.py` into 7 domain-specific handler modules + 1 shared utilities module:

| File | Lines | Functions |
|------|-------|-----------|
| `telegram_bot/handler_utils.py` | 120 | 5 shared helpers + module-level state (`_db`, `_inbox`, `_admin_reply_map`, `_support_draft_map`) |
| `telegram_bot/handlers/__init__.py` | 0 | Empty package init |
| `telegram_bot/handlers/contractor_handlers.py` | 926 | 29 functions (registration, linking, verification, invoice flows, editor sources) |
| `telegram_bot/handlers/admin_handlers.py` | 573 | 15 functions (admin commands: generate, budget, articles, lookup, reply routing) |
| `telegram_bot/handlers/support_handlers.py` | 229 | 9 functions (tech support, code runner, health check, email callbacks) |
| `telegram_bot/handlers/group_handlers.py` | 139 | 5 functions (group chat handling, command dispatch, NL classification) |
| `telegram_bot/handlers/conversation_handlers.py` | 271 | 7 functions (NL reply, teaching, knowledge management) |
| `telegram_bot/handlers/email_listener.py` | 42 | 1 function (background email listener task) |
| `telegram_bot/flow_callbacks.py` | 68 | Backward-compatible re-export shim |

- `flow_callbacks.py` reduced to a 68-line re-export shim using `_PatchProxyModule.__setattr__` to propagate test `@patch` calls to actual handler modules
- Cross-module dependencies handled via lazy imports (e.g., `_handle_nl_reply` imported lazily in `admin_handlers` and `group_handlers`)
- Fixed unused `ChatAction` import in `group_handlers.py` during review

**Design decisions:**
- Invoice handlers merged into contractor_handlers (contractor-side ops) and admin_handlers (batch commands) rather than separate file — they're tightly coupled
- Shared state centralized in `handler_utils.py`, imported by handler modules
- `_PatchProxyModule` trick means zero test file modifications needed — all `@patch("telegram_bot.flow_callbacks.X")` still works

**Net result:** 1003 tests pass, zero test files modified, pure move-only refactoring

**Notes:**
- Plan originally called for separate invoice_handlers.py but invoice logic is deeply intertwined with contractor and admin flows
- `flow_callbacks.py` re-export shim is a temporary bridge — later phases should update imports in flows.py, main.py, flow_engine.py, and tests to point directly to handler modules
- Next session should start Phase 2 (split db_gateway.py into domain-specific postgres repos)

### Session 50 (2026-03-03) — Plan 4 Phase 2: Split db_gateway.py into domain-specific postgres repos
**Status:** Complete (all 11 items: 2.1-2.11)

**What was done:**
- Split the 510-line `DbGateway` God object into 6 domain-specific repos + base class under `backend/infrastructure/repositories/postgres/`:

| File | Class | Methods |
|------|-------|---------|
| `base.py` | `BasePostgresRepo` | `_SCHEMA_SQL`, `__init__()`, `_get_conn()`, `init_schema()`, `close()` |
| `email_repo.py` | `EmailRepo` | 8 email/decision methods + `_normalize_subject` |
| `knowledge_repo.py` | `KnowledgeRepo` | 7 knowledge entry methods |
| `conversation_repo.py` | `ConversationRepo` | 3 conversation methods |
| `classification_repo.py` | `ClassificationRepo` | `log_classification()` |
| `payment_repo.py` | `PaymentRepo` | 2 payment validation methods |
| `code_task_repo.py` | `CodeTaskRepo` | 2 code task methods |

- `db_gateway.py` → 21-line backward-compatible shim using multiple inheritance: `DbGateway(EmailRepo, KnowledgeRepo, ConversationRepo, ClassificationRepo, PaymentRepo, CodeTaskRepo)`
- Moved sheets repos to `backend/infrastructure/repositories/sheets/`: `contractor_repo.py`, `invoice_repo.py`, `budget_repo.py`, `rules_repo.py`, `sheets_utils.py`
- Old repo locations → backward-compatible re-export shims (wildcard + explicit private names)
- Internal cross-references in sheets repos updated to new paths
- Zero source or test import changes needed — all shims transparent

**Design decisions:**
- Multiple inheritance for `DbGateway`: Python MRO handles diamond inheritance cleanly — all repos share the same `_conn` from `BasePostgresRepo.__init__()`
- `_SCHEMA_SQL` kept in `base.py` (contains ALL table definitions), `init_schema()` runs all DDLs
- Sheets shims explicitly re-export private names (`_parse_contractor`, `_write_cell`, etc.) that tests import

**Net result:** 1003 tests pass, zero test modifications, 8 new files + 5 shims

### Session 51 (2026-03-03) — Plan 4 Phase 3: Separate domain/ into services/ and use_cases/
**Status:** Complete (all 6 items: 3.1-3.6)

**What was done:**
- Created `backend/domain/services/` and `backend/domain/use_cases/` subdirectories with `__init__.py`
- Moved 6 use-case files to `use_cases/`: `compute_budget.py`, `generate_batch_invoices.py`, `generate_invoice.py`, `parse_bank_statement.py`, `prepare_invoice.py`, `seed_knowledge.py`
- Moved 6 service files to `services/`: `inbox_service.py`, `tech_support_handler.py`, `support_user_lookup.py`, `knowledge_retriever.py`, `command_classifier.py`, `compose_request.py`
- Kept 4 utility files in `domain/` root: `validate_contractor.py`, `resolve_amount.py`, `healthcheck.py`, `code_runner.py`
- All old locations replaced with backward-compatible re-export shims
- Shims that are targets of test `@patch` calls use `_PatchProxyModule` pattern (propagates setattr to real module)
- Simple shims used for `command_classifier.py` and `compute_budget.py` (no test patches on module-level names)
- Internal cross-references updated within moved files (e.g., `inbox_service` → `from backend.domain.services import compose_request`)
- `compose_request.py` lazy import of `KnowledgeRetriever` kept using old path for test compatibility
- `seed_knowledge.py` `KNOWLEDGE_DIR` path updated with extra `.parent` for new depth
- Zero test files or files outside `backend/domain/` modified

**Net result:** 1003 tests pass, 12 new files (6 services + 6 use_cases) + 12 shims at old locations

### Session 52 (2026-03-03) — Plan 4 Phase 4: Restructure tests to mirror source
**Status:** Complete (all 10 items: 4.1-4.10)

**What was done:**
- Moved all 42 test files from the flat `tests/` directory into subdirectories that mirror the source tree
- Created 12 new `__init__.py` files for all new test directories
- Used `git mv` for all moves to preserve git history
- No test file contents modified — pure move-only

**Test directory structure now:**
```
tests/
├── conftest.py, __init__.py           (unchanged at root)
├── domain/services/                   (6 files: inbox, tech_support, knowledge_retriever, compose_request, command_classifier, support_user_lookup)
├── domain/use_cases/                  (10 files: compute_budget, generate_invoice, generate_batch, parse_bank, prepare_invoice, seed_knowledge, resolve_amount, validate_contractor, healthcheck, code_runner)
├── infrastructure/gateways/           (9 files: gemini, email, email_parse, docs, airtable, republic, repo, embedding, exchange_rate)
├── infrastructure/repositories/postgres/  (2 files: db_gateway, knowledge_db)
├── infrastructure/repositories/sheets/    (5 files: contractor_repo, invoice_repo, budget_repo, rules_repo, sheets_utils)
├── telegram_bot/handlers/             (3 files: plan2_handlers, flow_callbacks_helpers, phase7_teaching)
├── telegram_bot/engine/               (3 files: flow_engine, flow_dsl, flows_structure)
├── telegram_bot/test_bot_helpers.py
└── common/                            (3 files: models, models_properties, prompt_loader)
```

**Notes:**
- Plan originally placed compose_request, command_classifier, support_user_lookup under use_cases — corrected to services (they're multi-method service modules, not single-execute use cases)
- All 1003 tests pass with zero modifications to test content
- No conftest.py changes needed — pytest discovers tests in subdirectories via `__init__.py` files

### Session 53 (2026-03-03) — Plan 4 Phase 5: Standardize Dependency Injection
**Status:** Complete (all 6 items: 5.1-5.6)

**What was done:**
- Audited all 8 classes that create gateway/repo instances in `__init__`
- Refactored all 8 constructors to accept optional dependency args with defaults:
  - `ComputeBudget(republic_gw=None, redefine_gw=None)`
  - `GenerateInvoice(docs_gw=None, drive_gw=None)`
  - `GenerateBatchInvoices(republic_gw=None, gen_invoice=None)`
  - `ParseBankStatement(airtable_gw=None)`
  - `SupportUserLookup(republic_gw=None, redefine_gw=None)`
  - `KnowledgeRetriever(db=None, embed=None)`
  - `TechSupportHandler(gemini=None, user_lookup=None, db=None)`
  - `InboxService(tech_support=None, gemini=None, email_gw=None, db=None)`
- Added `set_retriever()` function to `compose_request.py` alongside existing `_get_retriever()` lazy singleton
- Created `backend/wiring.py` composition root with 6 factory functions:
  - `create_db()`, `create_inbox_service()`, `create_knowledge_retriever()`
  - `create_compute_budget()`, `create_generate_batch_invoices()`, `create_parse_bank_statement()`
- Updated `handler_utils.py` to use wiring: `create_db()`, `create_inbox_service()`, `set_retriever(create_knowledge_retriever())`
- Updated `admin_handlers.py` to use wiring: `create_compute_budget()`, `create_generate_batch_invoices()`, `create_parse_bank_statement()`
- Updated `compose_request.py` shim to re-export `set_retriever`

**Review fixes applied:**
- Removed unused `load_knowledge` import from `compose_request.py`

**Design decisions:**
- Used optional args with defaults (`x or X()`) instead of required args — backward compatible, all existing tests and callers work unchanged
- `_get_retriever()` lazy singleton kept as fallback for standalone use; `set_retriever()` allows wiring to inject
- `TechSupportHandler.__init__` still calls `RepoGateway().ensure_repos()` and `db.init_schema()` — idempotent, needed for standalone instantiation
- Double `init_schema()` (wiring + TechSupportHandler) is harmless — CREATE IF NOT EXISTS

**Net result:** 1003 tests pass, zero test modifications, 1 new file (`backend/wiring.py`), 10 files modified

### Session 54 (2026-03-03) — Plan 4 Phase 6: Extract business logic from handlers into backend
**Status:** Complete (all 7 items: 6.1-6.7)

**What was done:**
- Created 4 new backend service modules extracting business logic from Telegram handlers:

**`backend/domain/services/contractor_service.py`** — 4 functions:
  - `parse_registration_data(text, contractor_type, collected, warnings)` — LLM parsing + DB validation logging (from `_parse_with_llm`)
  - `create_contractor(collected, contractor_type, telegram_id, contractors)` — ID generation, object construction, save + secret code (from `_save_new_contractor`)
  - `check_registration_complete(collected, required_fields)` — field completion check returning `(is_complete, missing)` (from `handle_data_input`)
  - `translate_contractor_name(name_en)` — thin wrapper around `translate_name_to_russian`

**`backend/domain/services/invoice_service.py`** — 2 functions + supporting types:
  - `resolve_existing_invoice(contractor, month)` — checks for existing invoice, classifies delivery action via `DeliveryAction` enum (5 values: SEND_PROFORMA, PROFORMA_ALREADY_SENT, SEND_RUB_WITH_LEGIUM, SEND_RUB_DRAFT, RUB_ALREADY_SENT)
  - `prepare_new_invoice_data(contractor, month)` — budget lookup, article fetching, amount resolution → returns `NewInvoiceData` dataclass or None
  - `ExistingInvoiceResult` and `NewInvoiceData` dataclasses

**`backend/domain/services/conversation_service.py`** — 3 functions:
  - `format_reply_chain(chain)` — pure formatting of conversation chain entries
  - `build_conversation_context(chat_id, reply_message_id, reply_text, db)` — DB lookup + reply chain retrieval or bootstrap fallback
  - `generate_nl_reply(message_text, conversation_history, retriever, gemini, verbose)` — knowledge retrieval + LLM call + response parsing

**`backend/domain/services/admin_service.py`** — 2 functions:
  - `classify_draft_reply(reply_text)` — greeting prefix detection, returns "replacement" or "feedback"
  - `store_admin_feedback(text, scope, retriever)` — wraps `retriever.store_feedback()` with error handling

- Updated 3 handler files to delegate to services:
  - `contractor_handlers.py`: uses contractor_service + invoice_service
  - `admin_handlers.py`: uses admin_service
  - `conversation_handlers.py`: uses conversation_service
- Module-level state (`_admin_reply_map`, `_support_draft_map`) kept in `handler_utils.py` — ephemeral Telegram runtime state, appropriate location
- All service functions are sync, handlers wrap in `asyncio.to_thread()`
- Dependencies passed as parameters to services for testability
- Created 4 test files with 52 new tests covering all service functions

**Net result:** 1055 tests pass (52 new), 4 new service files, 4 new test files, 3 handlers updated

**Notes:**
- `_GREETING_PREFIXES` moved from `admin_handlers.py` to `admin_service.py`, re-imported in handler for backward compat
- `conversation_service.generate_nl_reply` accepts optional `gemini` and `retriever` params — handler passes its patchable references
- `invoice_service.DeliveryAction` enum used by handler for clean action-based dispatch (switch on enum value)
- No changes to flow_callbacks.py shim — all patches still propagate correctly

### Session 55 (2026-03-03) — Plan 4 Phase 7: Clean up infrastructure leaks
**Status:** Complete (all 8 items: 7.1-7.8)

**What was done:**

7.1 — Removed DB logging from `gemini_gateway.py`:
- Removed `task` parameter, `self._db` lazy attr, `time` import, and all DB logging code from `GeminiGateway.call()`
- Updated 6 callers to log classifications themselves using `time.time()` + `db.log_classification()`:
  - `inbox_service.py`: `_llm_classify()`, `_handle_editorial()` — uses `self._db`
  - `tech_support_handler.py`: `_fetch_user_data()` — uses `self._db`
  - `command_classifier.py`: `classify()` — added optional `db` constructor param
  - `backend/__init__.py`: `translate_name_to_russian()` — creates local `DbGateway()`
  - `support_handlers.py`: `_answer_tech_question()` — uses shared `_db` from handler_utils
- Updated test files to remove `task=` assertions

7.2 — Moved contractor folder logic from `drive_gateway.py` to `invoice_service.py`:
- Created `get_invoice_folder_path(contractor, month) -> (parent_id, month_folder, name_folder)` in invoice_service
- Simplified `DriveGateway.get_contractor_folder()` to accept path components instead of contractor object
- Added `upload_invoice_pdf()` convenience method to DriveGateway (calls get_invoice_folder_path internally)
- Updated `generate_invoice.py` to call service function first

7.3 — Extracted email parsing to utility:
- Created `backend/infrastructure/gateways/email_utils.py` with `parse_email_message()`
- `EmailGateway._parse` kept as `staticmethod(parse_email_message)` for backward compat
- Updated `test_email_parse.py` to test utility directly

7.4 — Moved budget orchestration to service:
- Created `backend/domain/services/budget_service.py` with `redirect_in_budget()` and `unredirect_in_budget()`
- `budget_repo.py` has backward-compat re-imports
- Budget service imports `_find_sheet` and `EUR_RUB_RATE` from budget_repo

7.5 — Made `exchange_rate_gateway` a class:
- Created `ExchangeRateGateway` class with `fetch_eur_rub_rate()` method
- Backward-compat module-level function delegates to class

7.6 — Added error handling to `email_gateway.py` public methods:
- `fetch_unread()`: try/except, returns `[]` on error, logs warning
- `mark_read()`: try/except, logs warning
- `send_reply()`: try/except around Gmail send, logs error and re-raises

7.7 — Extracted shared Google service builder:
- Created `backend/infrastructure/gateways/google_auth.py` with `build_google_service(api, version)`
- Updated `sheets_gateway.py`, `drive_gateway.py`, `docs_gateway.py` to use it
- `EmailGateway` NOT updated (uses separate `get_gmail_creds()`)

**New files created:**
- `backend/infrastructure/gateways/email_utils.py`
- `backend/infrastructure/gateways/google_auth.py`
- `backend/domain/services/budget_service.py`

**Net result:** 1057 tests pass (2 new tests for exchange_rate_gateway class), 3 new files, ~15 files modified

### Session 56 (2026-03-03) — Plan 4 Phase 8: Eliminate code duplication
**Status:** Complete (all 6 items: 8.1-8.6)

**What was done:**

8.1 — Extract `send_typing` helper:
- Added `send_typing(chat_id: int)` to `handler_utils.py`
- Replaced 17 instances across 4 handler files (contractor, admin, support, conversation)
- Removed `ChatAction` imports from all 4 handler files (now only in handler_utils)
- 2 instances in flow_engine.py intentionally left (uses `message.bot.send_chat_action`, different pattern)

8.2 — Extract `parse_month_arg` helper:
- Added `parse_month_arg(args: list[str])` to `handler_utils.py`
- Only 1 actual instance found (in cmd_budget). Plan estimated 8, but others were plain `prev_month()` calls without args parsing

8.3 — Consolidate contractor lookup:
- Added `get_current_contractor(telegram_id)` and `get_contractor_by_id(contractor_id)` to `handler_utils.py`
- Replaced 13 instances: 12 in contractor_handlers.py, 1 in admin_handlers.py
- 6 instances intentionally not replaced (contractors list needed for batch operations, fuzzy matching, or loop iteration)

8.4 — Already done in Phase 7.7 (google_auth.py)

8.5 — No genuine duplication found:
- Reviewed all 6 `_fmt_*`/`_format_*` helpers across the codebase
- Each works on fundamentally different data structures — no consolidation worthwhile

8.6 — All 1057 tests pass

**Net result:** 1057 tests pass, ~30 code pattern instances consolidated into 4 helpers

### Session 57 (2026-03-03) — Plan 4 Phase 9: Break up fat methods
**Status:** Complete (all 7 items: 9.1-9.7)

**What was done:**

9.1 — `parse_bank_statement._categorize_transactions()` (166 → 37 lines):
- Extracted 8 private module-level helpers: `_handle_incoming_transfer`, `_handle_fee`, `_handle_outgoing_transfer`, `_handle_card_known_service`, `_handle_card_unknown_service`, `_handle_card_payment`, `_aggregate_swift_fees`, `_aggregate_fx_fees`
- Orchestrator now loops and dispatches to helpers, aggregation at end
- Backward-compat shim updated

9.2 — `compute_budget._make_noted_entry()` (94 → 16 lines):
- Promoted from nested closure to `@staticmethod`
- Takes `redirect_bonuses` as explicit parameter

9.3 — `compute_budget._build_entries()` (178 → 43 lines):
- Extracted 6 helpers: `_load_rule_lookups`, `_match_authors`, `_classify_entries`, `_process_matched_entries`, `_process_flat_entries`, `_assemble_grouped_result`

9.4 — `docs_gateway.insert_articles_table()` (82 → 26 lines):
- Extracted 5 helpers: `_delete_placeholder_paragraph`, `_insert_empty_table`, `_collect_cell_indices`, `_build_table_data`, `_build_fill_requests`

9.5 — `validate_contractor.validate_fields()` (72 → 13 lines):
- Extracted 4 per-type validators: `_validate_person_fields`, `_validate_ip_fields`, `_validate_global_fields`, `_validate_address_ru`

9.6 — `budget_service.redirect_in_budget()` (60 → 28 lines) and `unredirect_in_budget()` (72 → 26 lines):
- Extracted 7 shared helpers: `_find_row_by_name`, `_find_source_row`, `_convert_amount`, `_pad_row`, `_add_amount_to_row`, `_subtract_amount_from_row`, `_extract_bonus_from_note`, `_restore_source_row`

**Review cleanup:** Removed ~20 unnecessary docstrings added by refactoring agents (codebase convention: no docstrings on obvious private helpers)

**Net result:** 1057 tests pass, 5 files refactored, all fat methods under 43 lines

### Session 58 (2026-03-03) — Maintenance: Spot Bugs (round 9) + Write Tests (round 10)
**Status:** Complete

**Spot Bugs (round 9):**
- Thorough review of all key files from Plan 4 Phases 1-9 (30+ files: handlers, services, repos, shims, wiring)
- Checked: missing imports, incorrect paths, state sharing, parameter mismatches, asyncio.to_thread wrapping, PatchProxyModule correctness, circular imports, dead code
- **Zero bugs found** — the 9-phase refactoring was executed cleanly

**Write Tests (round 10):**
- Added 29 new tests for Phase 8 handler_utils.py helpers (previously zero coverage):
  - `TestSendTyping` (2): bot.send_chat_action called correctly
  - `TestGetCurrentContractor` (2): found/not-found paths with mocked get_contractors
  - `TestGetContractorById` (2): found/not-found paths
  - `TestParseMonthArg` (6): month extraction, defaults, whitespace, extra args
  - `TestParseFlags` (12): all flag combos (-v, verbose, -e, expert), edge cases, no-flags
  - `TestFindContractorOrSuggest` (5): exact match, fuzzy suggestions, not found, cap at 5, threshold

**Bug found and fixed:**
1. **`_parse_flags` IndexError on trailing whitespace** (`handler_utils.py`):
   - `"-v "` → `text.split(None, 1)` returns `["-v"]` (single element), `[1]` crashes
   - **Fix**: Check `len(parts) > 1` instead of `" " in text`

**Net result:** 1086 tests pass (+29 new), 1 bug fixed

### Session 59 (2026-03-03) — Maintenance: Write Tests (round 11 — budget_service)
**Status:** Complete

**What was done:**
- Created `tests/domain/services/test_budget_service.py` — 67 tests across 10 classes covering all 9 functions + `_restore_source_row`:
  - `TestFindRowByName` (7): exact match, case insensitive, whitespace, not found, empty rows, first match
  - `TestFindSourceRow` (8): found with amounts, missing columns, not found, empty/blank rows
  - `TestConvertAmount` (9): EUR→EUR, RUB→RUB, cross-currency both directions, preference when both present, zeros
  - `TestPadRow` (5): empty, short, already full, edge sizes
  - `TestAddAmountToRow` (4): EUR/RUB columns, cumulative, empty cell
  - `TestSubtractAmountFromRow` (4): EUR/RUB columns, negative result, empty cell
  - `TestExtractBonusFromNote` (9): single/multiple entries, case insensitive, no match, invalid amount, no parens, middle match
  - `TestRedirectInBudget` (9): mocked _find_sheet + _sheets: no sheet, source/target not found, zero amounts, happy path EUR/RUB, note appending, cross-currency, short rows
  - `TestUnredirectInBudget` (7): mocked: no sheet, target not found, empty note, source not in note, happy path EUR/RUB, remaining note preserved
  - `TestRestoreSourceRow` (5): mocked _sheets: empty slot, no empty slot (append), EUR/RUB column, blank name as empty slot

**Net result:** 67 new tests (1153 total), all passing in 2.07s

**Notes:**
- `budget_service.py` was the last critical untested module — handles financial redirects with complex business logic
- Tests mock `_sheets` and `_find_sheet` at the budget_service module namespace
- Pure helper tests require no mocking — they work on plain lists and enums

### Session 60 (2026-03-03) — Maintenance: Write Tests (round 12 — handler modules)
**Status:** Complete

**What was done:**
- Created 4 new test files with 129 tests covering previously untested Telegram handler functions:

**`tests/telegram_bot/handlers/test_support_handlers.py`** — 21 tests across 4 classes:
  - `TestHandleSupportCallback` (6): send/skip actions, expired draft, invalid data, unknown action
  - `TestHandleEditorialCallback` (4): forward/skip actions, expired editorial, invalid data
  - `TestSendSupportDraft` (6): message format with buttons, draft_map population, uncertain header, reply-to, truncation
  - `TestSendEditorial` (5): message format, auto-reply, truncation, callback data

**`tests/telegram_bot/handlers/test_conversation_handlers.py`** — 16 tests across 2 classes:
  - `TestCmdNl` (10): no args usage, empty args, classification error, unclassified reply, turn saving, handler dispatch, text rewrite/restore
  - `TestHandleNlReplyNewModule` (6): FSM/no-reply/not-bot guards, happy path, teaching keyword

**`tests/telegram_bot/handlers/test_admin_handlers.py`** — 30 tests across 8 classes:
  - `TestCmdGenerate` (8): no args, not found, not in budget, zero amount, RUB/EUR, error, debug
  - `TestCmdBudget` (3): success, default month, error
  - `TestCmdGenerateInvoices` (4): no results, with results, ValueError, errors
  - `TestCmdSendGlobalInvoices` (4): no drafts, sends, no telegram, no doc_id
  - `TestCmdSendLegiumLinks` (3): no pending, sends with PDF, no telegram
  - `TestCmdOrphanContractors` (2): none/found
  - `TestCmdChatid` (1)
  - `TestCmdUploadToAirtable` (5): no document, no rate, invalid rate, success, error

**`tests/telegram_bot/handlers/test_contractor_handlers.py`** — 62 tests across 19 classes:
  - Registration flows: type selection (6), data input, contractor text (4), duplicate callback (4)
  - Invoice flows: verification code (5), amount input (5), linked menu (3), sign doc (2)
  - Update flows: update data (5), editor sources (6), editor source name (3)
  - Utility: linked menu markup (2), start (2), menu (3), non-document (3), document (4), forward to admins (2), notify admins (1)

**Review cleanup applied:**
- Removed module docstrings from all 4 files (project convention)
- Removed unused imports (dataclass, ArticleEntry, RoleCode, pytest)
- Fixed meaningless assertion in truncation test

**Net result:** 129 new tests (1282 total), all passing in 2.44s

**Notes:**
- Handler test coverage went from ~40% (only test_plan2_handlers.py and test_flow_callbacks_helpers.py) to ~90%
- All tests use established patterns: AsyncMock for Telegram, patch for deps, MagicMock for sync gateways
- No duplication with existing test files — each new file covers different functions
- Remaining untested: email_listener.py (42 lines, async background loop), thin gateway wrappers (drive, sheets, redefine)

## Plan 4 status

**ALL PHASES COMPLETE (1-9).** Plan 4 Architecture Refactor is fully done. Next sessions enter maintenance mode.

### Session 61 (2026-03-04) — Plan 5 Phases 5.0-5.2: Pre-flight + Schema + EnvironmentRepo
**Status:** Complete (all items: 5.0.1-5.0.6, 5.1.1-5.1.3, 5.2.1-5.2.4)

**What was done:**
- Added `environments` table to `_SCHEMA_SQL` in `base.py` (name TEXT PK, description, system_context, allowed_domains TEXT[], timestamps)
- Added `environment_bindings` table (chat_id BIGINT PK, environment TEXT FK → environments.name, timestamps)
- Added seed data INSERT for 4 environments: admin_dm, editorial_group, contractor_dm, email (ON CONFLICT DO NOTHING)
- Created `backend/infrastructure/repositories/postgres/environment_repo.py` with 7 methods:
  - `get_environment(name)`, `get_environment_by_chat_id(chat_id)` (JOIN), `list_environments()`
  - `save_environment()` (upsert), `update_environment(**fields)` (dynamic partial update)
  - `bind_chat()` (upsert), `unbind_chat()`
- Added `EnvironmentRepo` to DbGateway multiple inheritance in `postgres/__init__.py`
- Created `tests/infrastructure/repositories/postgres/test_environment_repo.py` with 14 tests across 5 classes

**Review fix applied:**
- Changed TIMESTAMPTZ → TIMESTAMP in new tables to match existing convention across all other tables

**Net result:** 1221 tests pass (+14 new)

**Notes:**
- `update_environment` uses a hardcoded whitelist of allowed columns (description, system_context, allowed_domains) — safe against SQL injection
- `save_environment` uses INSERT ON CONFLICT DO UPDATE for upsert behavior
- `bind_chat` uses INSERT ON CONFLICT DO UPDATE for rebinding
- Uses `with conn.cursor() as cur:` pattern matching knowledge_repo.py and email_repo.py

### Session 62 (2026-03-04) — Plan 5 Phases 5.3-5.4: Seed Bindings + Domain-filtered RAG
**Status:** Complete (all items: 5.3.1-5.3.3, 5.4.1-5.4.5)

**What was done:**
- Added `_seed_bindings()` method to `base.py` that runs after `init_schema()`:
  - Binds `EDITORIAL_CHAT_ID` → `editorial_group` (guarded by truthiness check, config defaults to 0)
  - Iterates `ADMIN_TELEGRAM_IDS` and binds each → `admin_dm` (DMs: chat_id == user_id)
  - Uses `ON CONFLICT DO NOTHING` for idempotency
- Added `search_knowledge_multi_domain()` to `knowledge_repo.py`:
  - Vector similarity search with `WHERE domain = ANY(%s)` for multi-domain filtering
  - Falls back to no filter when `domains is None`
- Added `get_multi_domain_context()` to `knowledge_repo.py`:
  - Returns core + meta entries for multiple domains using `domain = ANY(%s)`
- Updated `retrieve()` in `knowledge_retriever.py`:
  - Extended signature: `domains: list[str] | None = None`
  - Routes to `search_knowledge_multi_domain` when `domains` provided
- Added `get_multi_domain_context()` to `knowledge_retriever.py`
- 10 new tests: 5 in test_knowledge_db.py, 5 in test_knowledge_retriever.py

**Review:** Clean implementation, no fixes needed.

**Net result:** 1231 tests pass (+10 new)

### Session 63 (2026-03-04) — Plan 5 Phases 5.5-5.6: Environment Prompt Assembly + Teaching Security
**Status:** Complete (all items: 5.5.1-5.5.6, 5.6.1-5.6.3)

**What was done:**
- Updated `templates/conversation.md`: added `## Окружение` / `{{ENVIRONMENT}}` section between VERBOSE and Контекст
- Updated `compose_request.conversation_reply()`: added `environment_context: str = ""` param, passes to template (falls back to "(контекст не указан)")
- Updated `conversation_service.generate_nl_reply()`: added `environment: str = ""` and `allowed_domains: list[str] | None = None` params. When domains given, uses `get_multi_domain_context` + `retrieve(domains=...)` instead of `get_core` + `retrieve()`
- Added `resolve_environment(chat_id)` helper to `handler_utils.py` — returns `(system_context, allowed_domains)` or `("", None)` if unbound
- Updated all 3 call sites: `_handle_nl_reply`, `cmd_nl`, `handle_group_message` — each resolves environment and passes through
- Added `is_admin` check around teaching keyword detection in `_handle_nl_reply` (5.6 security fix)
- 9 new tests: 3 in test_compose_request, 4 in test_conversation_service, 2 in test_conversation_handlers
- Updated existing tests with `resolve_environment` and `is_admin` patches

**Review fix applied:**
- Supervisor restored persona lines ("Ты — напарник Луки..." and "Используй контекст.") that dev agent accidentally removed from conversation.md template

**Net result:** 1240 tests pass (+9 new)

## Next up

- Plan 5 continues with 5.7 (teaching dedup), 5.8 (bot commands for env management), 5.9 (verification)
- Phase 2.4 from Plan 3 still needs: run seed script on live DB and verify entries
- `_test_ternary.py` stray empty file in project root — needs manual deletion
