# Architecture Refactor Plan

> Checklistable plan for restructuring the Republic Agent codebase.
> Agents: mark items `[x]` as you complete them. Pick up where the previous session left off.

## Target Structure

```
backend/
├── domain/
│   ├── models/                  # entities, value objects
│   ├── services/                # reusable domain logic (multi-method, stateful-light)
│   └── use_cases/               # orchestration (one execute(), thin)
├── infrastructure/
│   ├── gateways/                # external API wrappers (pure I/O, zero business logic)
│   └── repositories/
│       ├── postgres/            # split from db_gateway.py by domain
│       └── sheets/              # Google Sheets repos (mostly clean already)
common/
├── models.py                    # keep as-is (healthy)
├── config.py                    # keep as-is (clean)
└── prompt_loader.py             # keep as-is
telegram_bot/
├── handlers/                    # split from flow_callbacks.py by domain
├── flow_dsl.py
├── flow_engine.py
├── flows.py
├── replies.py
├── bot_helpers.py
└── main.py
tests/
├── conftest.py
├── domain/
│   ├── services/
│   └── use_cases/
├── infrastructure/
│   ├── gateways/
│   └── repositories/
│       ├── postgres/
│       └── sheets/
├── telegram_bot/
│   ├── handlers/
│   └── engine/
└── common/
```

---

## Phase 1: Split `flow_callbacks.py` into handler modules

> Goal: break the 2,105-line monolith into domain-specific files under `telegram_bot/handlers/`.
> Rule: MOVE code only, no logic changes. Tests must keep passing after each step.

- [x] 1.1 Create `telegram_bot/handlers/__init__.py`
- [x] 1.2 Extract contractor handlers → `telegram_bot/handlers/contractor_handlers.py` (926 lines, 29 functions)
  - All contractor registration, linking, verification, invoice flow callbacks, editor source management
- [x] 1.3 Invoice handlers merged into contractor_handlers (tightly coupled) and admin_handlers (batch commands)
  - Contractor-side invoice ops in contractor_handlers.py, batch commands in admin_handlers.py
- [x] 1.4 Extract admin handlers → `telegram_bot/handlers/admin_handlers.py` (573 lines, 15 functions)
  - `handle_admin_reply`, `_handle_draft_reply`, admin command handlers (budget, articles, bank, generate, lookup, etc.)
- [x] 1.5 Extract support handlers → `telegram_bot/handlers/support_handlers.py` (229 lines, 9 functions)
  - `_answer_tech_question`, `cmd_support`, `cmd_code`, `cmd_health`, email callback handlers
- [x] 1.6 Extract group handlers → `telegram_bot/handlers/group_handlers.py` (139 lines, 5 functions)
  - `handle_group_message`, `_dispatch_group_command`, `_extract_bot_mention`, command dicts
- [x] 1.7 Extract conversation/teaching handlers → `telegram_bot/handlers/conversation_handlers.py` (271 lines, 7 functions)
  - `cmd_nl`, `cmd_teach`, `cmd_knowledge`, `cmd_forget`, `cmd_kedit`, `_handle_nl_reply`, `_format_reply_chain`
- [x] 1.8 Extract email listener → `telegram_bot/handlers/email_listener.py` (42 lines, 1 function)
  - `email_listener_task` background loop
- [x] 1.9 Shared helpers in `telegram_bot/handler_utils.py` (120 lines)
  - Module-level state (`_db`, `_inbox`, `_admin_reply_map`, `_support_draft_map`)
  - Shared helpers: `_safe_edit_text`, `_send_html`, `_save_turn`, `_parse_flags`, `_find_contractor_or_suggest`
- [x] 1.10 `flow_callbacks.py` reduced to 68-line backward-compatible re-export shim
  - Uses `_PatchProxyModule.__setattr__` to propagate test `@patch` calls to actual handler modules
  - All existing imports from `telegram_bot.flow_callbacks` continue to work unchanged
- [x] 1.11 Full test suite — all 1003 tests pass

---

## Phase 2: Split `db_gateway.py` into domain-specific postgres repos

> Goal: break the 509-line God object into focused stores under `repositories/postgres/`.
> Rule: shared connection logic stays in a base module. Each store owns its tables.

- [x] 2.1 Create `backend/infrastructure/repositories/postgres/__init__.py`
- [x] 2.2 Extract base connection → `postgres/base.py`
  - `BasePostgresRepo` with `_SCHEMA_SQL`, `__init__()`, `_get_conn()`, `init_schema()`, `close()`
- [x] 2.3 Extract email store → `postgres/email_repo.py`
  - `EmailRepo(BasePostgresRepo)` with 8 methods + `_normalize_subject` helper
- [x] 2.4 Extract knowledge store → `postgres/knowledge_repo.py`
  - `KnowledgeRepo(BasePostgresRepo)` with 7 methods
- [x] 2.5 Extract conversation store → `postgres/conversation_repo.py`
  - `ConversationRepo(BasePostgresRepo)` with 3 methods
- [x] 2.6 Extract classification store → `postgres/classification_repo.py`
  - `ClassificationRepo(BasePostgresRepo)` with `log_classification()`
- [x] 2.7 Extract payment validation store → `postgres/payment_repo.py`
  - `PaymentRepo(BasePostgresRepo)` with 2 methods
- [x] 2.8 Extract code task store → `postgres/code_task_repo.py`
  - `CodeTaskRepo(BasePostgresRepo)` with 2 methods
- [x] 2.9 `db_gateway.py` → backward-compatible shim via multiple inheritance (`DbGateway(EmailRepo, KnowledgeRepo, ...)`)
  - Zero source/test import changes needed
- [x] 2.10 Move sheets repos → `backend/infrastructure/repositories/sheets/`
  - `contractor_repo.py`, `invoice_repo.py`, `budget_repo.py`, `rules_repo.py`, `sheets_utils.py`
  - Old locations → backward-compatible re-export shims
- [x] 2.11 Full test suite — all 1003 tests pass

---

## Phase 3: Separate `domain/` into `services/` and `use_cases/`

> Goal: make the convention explicit — use-cases have one `execute()`, services have query/action methods, utilities are module-level functions.
> Rule: directory move + minor interface cleanup. No logic changes.

- [x] 3.1 Create `backend/domain/services/` and `backend/domain/use_cases/`
- [x] 3.2 Move use-case files → `use_cases/`
  - `compute_budget.py`, `generate_batch_invoices.py`, `generate_invoice.py`, `parse_bank_statement.py`, `prepare_invoice.py`, `seed_knowledge.py`
- [x] 3.3 Move service files → `services/`
  - `inbox_service.py`, `tech_support_handler.py`, `support_user_lookup.py`, `knowledge_retriever.py`, `command_classifier.py`, `compose_request.py`
- [x] 3.4 Keep utility files in `domain/` root (or create `domain/utils/`)
  - `validate_contractor.py`, `resolve_amount.py`, `healthcheck.py`, `code_runner.py`
- [x] 3.5 Update all imports across codebase
- [x] 3.6 Run full test suite — all tests pass

---

## Phase 4: Restructure tests to mirror source

> Goal: tests/ directory mirrors the source tree.
> Rule: move files, fix imports if any. No test logic changes.

- [x] 4.1 Create directory structure:
  ```
  tests/domain/services/
  tests/domain/use_cases/
  tests/infrastructure/gateways/
  tests/infrastructure/repositories/postgres/
  tests/infrastructure/repositories/sheets/
  tests/telegram_bot/handlers/
  tests/telegram_bot/engine/
  tests/common/
  ```
- [x] 4.2 Move domain service tests → `tests/domain/services/`
  - `test_inbox_service.py`, `test_tech_support_handler.py`, `test_knowledge_retriever.py`, `test_compose_request.py`, `test_command_classifier.py`, `test_support_user_lookup.py`
- [x] 4.3 Move domain use-case tests → `tests/domain/use_cases/`
  - `test_compute_budget.py`, `test_generate_invoice.py`, `test_generate_batch_invoices.py`, `test_parse_bank_statement.py`, `test_prepare_invoice.py`, `test_seed_knowledge.py`, `test_validate_contractor.py`, `test_resolve_amount.py`, `test_healthcheck.py`, `test_code_runner.py`
- [x] 4.4 Move gateway tests → `tests/infrastructure/gateways/`
  - `test_gemini_gateway.py`, `test_email_gateway.py`, `test_email_parse.py`, `test_docs_gateway.py`, `test_airtable_gateway.py`, `test_republic_gateway.py`, `test_repo_gateway.py`, `test_embedding_gateway.py`, `test_exchange_rate_gateway.py`
- [x] 4.5 Move postgres repo tests → `tests/infrastructure/repositories/postgres/`
  - `test_db_gateway.py`, `test_knowledge_db.py`
- [x] 4.6 Move sheets repo tests → `tests/infrastructure/repositories/sheets/`
  - `test_contractor_repo.py`, `test_invoice_repo.py`, `test_budget_repo.py`, `test_rules_repo.py`, `test_sheets_utils.py`
- [x] 4.7 Move telegram bot tests → `tests/telegram_bot/`
  - `handlers/`: `test_plan2_handlers.py`, `test_flow_callbacks_helpers.py`, `test_phase7_teaching.py`
  - `engine/`: `test_flow_engine.py`, `test_flow_dsl.py`, `test_flows_structure.py`
  - `test_bot_helpers.py`
- [x] 4.8 Move common tests → `tests/common/`
  - `test_models.py`, `test_models_properties.py`, `test_prompt_loader.py`
- [x] 4.9 Add `__init__.py` to all new test directories
- [x] 4.10 Run full test suite — all 1003 tests pass

---

## Phase 5: Standardize dependency injection

> Goal: constructor injection everywhere. Testable, swappable.
> Rule: change `__init__` signatures, update callers (composition root).

- [x] 5.1 Audit all classes that instantiate gateways/repos in `__init__`
  - `ComputeBudget`, `GenerateBatchInvoices`, `GenerateInvoice`, `InboxService`, `TechSupportHandler`, `SupportUserLookup`, `KnowledgeRetriever`, `ParseBankStatement`
- [x] 5.2 Refactor each to accept dependencies as optional constructor args
  - Pattern: `def __init__(self, republic_gw: RepublicGateway | None = None, ...)` → `self._x = x or X()`
  - Backward-compatible: calling `Class()` with no args still works
- [x] 5.3 Added `set_retriever()` to `compose_request.py` — kept `_get_retriever()` lazy fallback for standalone use
- [x] 5.4 Create composition root → `backend/wiring.py`
  - 6 factory functions: `create_db`, `create_inbox_service`, `create_knowledge_retriever`, `create_compute_budget`, `create_generate_batch_invoices`, `create_parse_bank_statement`
- [x] 5.5 Update handler files to use composition root
  - `handler_utils.py`: uses `create_db()`, `create_inbox_service()`, `set_retriever(create_knowledge_retriever())`
  - `admin_handlers.py`: uses `create_compute_budget()`, `create_generate_batch_invoices()`, `create_parse_bank_statement()`
- [x] 5.6 Run full test suite — all 1003 tests pass

---

## Phase 6: Extract business logic from handlers into backend

> Goal: handlers become thin — parse input → call backend → format reply → send.
> Rule: logic moves to services/use_cases, handlers shrink to ~10-20 lines each.

- [x] 6.1 Create `backend/domain/services/contractor_service.py`
  - Extracted: `parse_registration_data()`, `create_contractor()`, `check_registration_complete()`, `translate_contractor_name()`
- [x] 6.2 Create `backend/domain/services/invoice_service.py`
  - Extracted: `resolve_existing_invoice()` with `DeliveryAction` enum, `prepare_new_invoice_data()` with `NewInvoiceData` dataclass
- [x] 6.3 Create `backend/domain/services/conversation_service.py`
  - Extracted: `build_conversation_context()`, `generate_nl_reply()`, `format_reply_chain()`
- [x] 6.4 Create `backend/domain/services/admin_service.py`
  - Extracted: `classify_draft_reply()` with `_GREETING_PREFIXES`, `store_admin_feedback()`
- [x] 6.5 Module-level state (`_admin_reply_map`, `_support_draft_map`) kept in `handler_utils.py`
  - These are ephemeral Telegram runtime state — appropriate in the handler layer, not in backend services or DB
- [x] 6.6 Write tests for new services
  - 52 new tests across 4 test files: `test_contractor_service.py`, `test_invoice_service.py`, `test_conversation_service.py`, `test_admin_service.py`
- [x] 6.7 Run full test suite — all 1055 tests pass

---

## Phase 7: Clean up infrastructure leaks

> Goal: gateways are pure I/O wrappers, repos don't orchestrate.
> Rule: targeted fixes, one at a time.

- [x] 7.1 Remove DB logging from `gemini_gateway.py` — make callers responsible for logging classifications
  - Removed `task` parameter and all DB logging from `GeminiGateway.call()`, updated 6 callers to log classifications themselves
- [x] 7.2 Move contractor folder logic from `drive_gateway.py` → `invoice_service.py`
  - Created `get_invoice_folder_path()` in invoice_service, simplified `get_contractor_folder()` to accept path components
- [x] 7.3 Extract email parsing from `email_gateway._parse()` → utility function
  - Created `email_utils.py` with `parse_email_message()`, kept `_parse` as staticmethod alias for backward compat
- [x] 7.4 Move `redirect_in_budget` / `unredirect_in_budget` orchestration from `budget_repo.py` → `budget_service.py`
  - Created `backend/domain/services/budget_service.py` with both orchestration functions
- [x] 7.5 Make `exchange_rate_gateway` a class (consistent with other gateways)
  - Created `ExchangeRateGateway` class, kept backward-compat module-level function
- [x] 7.6 Add error handling to `email_gateway.py` public methods (fetch_unread, mark_read, send_reply)
  - `fetch_unread()` returns `[]` on error, `mark_read()` logs warning, `send_reply()` logs and re-raises
- [x] 7.7 Extract shared Google service builder from sheets/drive/docs gateways
  - Created `google_auth.py` with `build_google_service()`, updated 3 gateways
- [x] 7.8 Run full test suite — all 1057 tests pass

---

## Phase 8: Eliminate code duplication

> Goal: DRY up the repeated patterns identified in the review.
> Rule: extract helpers, do NOT over-abstract.

- [ ] 8.1 Extract `_with_typing(chat_id, coro)` helper — replaces 33 instances of chat-action + try/except
- [ ] 8.2 Extract month-arg parsing helper — replaces 8 instances of `args[1] if len(args) > 1 else prev_month()`
- [ ] 8.3 Consolidate contractor lookup — handlers call `ContractorService.lookup()` instead of `get_contractors()` + `find_*` (21 occurrences)
- [ ] 8.4 Extract shared Google service factory for sheets/drive/docs gateways
- [ ] 8.5 Consolidate markdown formatting helpers (4 separate `_fmt_*` / `_format_*` implementations)
- [ ] 8.6 Run full test suite — all tests pass

---

## Phase 9: Break up fat methods

> Goal: no method longer than ~40 lines. Extract sub-steps with clear names.
> Rule: extract private helpers within the same file. Don't create new files for internal decomposition.

- [ ] 9.1 `parse_bank_statement._categorize_transactions()` (166 lines) → extract per-category matchers
- [ ] 9.2 `compute_budget._make_noted_entry()` (94 lines) → separate entry building from bonus calculation
- [ ] 9.3 `compute_budget._build_entries()` (86 lines) → separate lookup, matching, routing
- [ ] 9.4 `docs_gateway.insert_articles_table()` (82 lines) → extract step helpers
- [ ] 9.5 `validate_contractor.validate_fields()` (72 lines) → extract per-type validators
- [ ] 9.6 `budget_repo.redirect_in_budget()` (60 lines) and `unredirect_in_budget()` (72 lines) → decompose (after Phase 7.4 moves orchestration out)
- [ ] 9.7 Run full test suite — all tests pass

---

## Execution Notes

**Order matters:** Phases 1-4 are mechanical moves (low risk, high impact). Phases 5-6 change interfaces (medium risk). Phases 7-9 are targeted cleanups (low risk, lower impact).

**Between every phase:** run `pytest` and confirm all tests pass before starting the next phase.

**Safe to parallelize:** Phases 7, 8, 9 are independent and can run concurrently.

**Each phase = one commit** with a clear message like `refactor: split flow_callbacks.py into domain handler modules`.
