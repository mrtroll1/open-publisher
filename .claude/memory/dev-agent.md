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

## Next up

- Maintenance mode continues. Priorities: polish UX, improve prompts.
