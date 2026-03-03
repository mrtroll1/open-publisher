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

- [ ] 2.1 Create `backend/infrastructure/repositories/postgres/__init__.py`
- [ ] 2.2 Extract base connection → `postgres/base.py`
  - `_get_conn()`, `_ensure_tables()` scaffold, shared connection pool
- [ ] 2.3 Extract email store → `postgres/email_repo.py`
  - `email_threads` table: `save_thread`, `find_thread_by_uid`
  - `email_decisions` table: `create_email_decision`, `update_decision_status`
- [ ] 2.4 Extract knowledge store → `postgres/knowledge_repo.py`
  - `knowledge_chunks` table: `upsert_chunk`, `search_knowledge`, `delete_chunk`, `list_all_chunks`
- [ ] 2.5 Extract conversation store → `postgres/conversation_repo.py`
  - `conversations` table: `save_conversation`, `get_conversation_by_message_id`, `get_reply_chain`
- [ ] 2.6 Extract classification store → `postgres/classification_repo.py`
  - `classifications` table: `log_classification`
- [ ] 2.7 Extract payment validation store → `postgres/payment_repo.py`
  - `payment_validations` table: `log_payment_validation`, `finalize_payment_validation`
- [ ] 2.8 Extract code task store → `postgres/code_task_repo.py`
  - `code_tasks` table: `create_code_task`
- [ ] 2.9 Update all imports across codebase (domain files, handlers, tests)
- [ ] 2.10 Move sheets repos → `backend/infrastructure/repositories/sheets/`
  - `contractor_repo.py`, `invoice_repo.py`, `budget_repo.py`, `rules_repo.py`, `sheets_utils.py`
- [ ] 2.11 Run full test suite — all tests pass

---

## Phase 3: Separate `domain/` into `services/` and `use_cases/`

> Goal: make the convention explicit — use-cases have one `execute()`, services have query/action methods, utilities are module-level functions.
> Rule: directory move + minor interface cleanup. No logic changes.

- [ ] 3.1 Create `backend/domain/services/` and `backend/domain/use_cases/`
- [ ] 3.2 Move use-case files → `use_cases/`
  - `compute_budget.py`, `generate_batch_invoices.py`, `generate_invoice.py`, `parse_bank_statement.py`, `prepare_invoice.py`, `seed_knowledge.py`
- [ ] 3.3 Move service files → `services/`
  - `inbox_service.py`, `tech_support_handler.py`, `support_user_lookup.py`, `knowledge_retriever.py`, `command_classifier.py`, `compose_request.py`
- [ ] 3.4 Keep utility files in `domain/` root (or create `domain/utils/`)
  - `validate_contractor.py`, `resolve_amount.py`, `healthcheck.py`, `code_runner.py`
- [ ] 3.5 Update all imports across codebase
- [ ] 3.6 Run full test suite — all tests pass

---

## Phase 4: Restructure tests to mirror source

> Goal: tests/ directory mirrors the source tree.
> Rule: move files, fix imports if any. No test logic changes.

- [ ] 4.1 Create directory structure:
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
- [ ] 4.2 Move domain service tests → `tests/domain/services/`
  - `test_inbox_service.py`, `test_tech_support_handler.py`, `test_knowledge_retriever.py`
- [ ] 4.3 Move domain use-case tests → `tests/domain/use_cases/`
  - `test_compute_budget.py`, `test_generate_invoice.py`, `test_generate_batch_invoices.py`, `test_parse_bank_statement.py`, `test_prepare_invoice.py`, `test_seed_knowledge.py`, `test_compose_request.py`, `test_validate_contractor.py`, `test_resolve_amount.py`, `test_healthcheck.py`, `test_command_classifier.py`, `test_code_runner.py`, `test_support_user_lookup.py`
- [ ] 4.4 Move gateway tests → `tests/infrastructure/gateways/`
  - `test_gemini_gateway.py`, `test_email_gateway.py`, `test_email_parse.py`, `test_docs_gateway.py`, `test_airtable_gateway.py`, `test_republic_gateway.py`, `test_repo_gateway.py`, `test_embedding_gateway.py`, `test_exchange_rate_gateway.py`
- [ ] 4.5 Move postgres repo tests → `tests/infrastructure/repositories/postgres/`
  - `test_db_gateway.py` (split to match new stores), `test_knowledge_db.py`
- [ ] 4.6 Move sheets repo tests → `tests/infrastructure/repositories/sheets/`
  - `test_contractor_repo.py`, `test_invoice_repo.py`, `test_budget_repo.py`, `test_rules_repo.py`, `test_sheets_utils.py`
- [ ] 4.7 Move telegram bot tests → `tests/telegram_bot/`
  - `handlers/`: `test_plan2_handlers.py`, `test_flow_callbacks_helpers.py`, `test_phase7_teaching.py`
  - `engine/`: `test_flow_engine.py`, `test_flow_dsl.py`, `test_flows_structure.py`
  - `test_bot_helpers.py`
- [ ] 4.8 Move common tests → `tests/common/`
  - `test_models.py`, `test_models_properties.py`, `test_prompt_loader.py`
- [ ] 4.9 Add `__init__.py` to all new test directories
- [ ] 4.10 Run full test suite — all tests pass

---

## Phase 5: Standardize dependency injection

> Goal: constructor injection everywhere. Testable, swappable.
> Rule: change `__init__` signatures, update callers (composition root).

- [ ] 5.1 Audit all classes that instantiate gateways/repos in `__init__`
  - `ComputeBudget`, `GenerateBatchInvoices`, `GenerateInvoice`, `InboxService`, `TechSupportHandler`, `SupportUserLookup`, `KnowledgeRetriever`, `ParseBankStatement`
- [ ] 5.2 Refactor each to accept dependencies as constructor args
  - Pattern: `def __init__(self, republic_gw: RepublicGateway, ...)`
- [ ] 5.3 Remove global lazy singleton in `compose_request.py` (`_get_retriever`)
- [ ] 5.4 Create composition root → `backend/wiring.py`
  - Factory functions that wire up all dependencies
  - Telegram handlers call `wiring.get_compute_budget()` etc.
- [ ] 5.5 Update handler files to use composition root
- [ ] 5.6 Run full test suite — all tests pass

---

## Phase 6: Extract business logic from handlers into backend

> Goal: handlers become thin — parse input → call backend → format reply → send.
> Rule: logic moves to services/use_cases, handlers shrink to ~10-20 lines each.

- [ ] 6.1 Create `backend/domain/services/contractor_service.py`
  - Extract: registration flow logic, validation orchestration, LLM parsing from contractor handlers
- [ ] 6.2 Create `backend/domain/services/invoice_service.py`
  - Extract: delivery logic, duplicate resolution, batch orchestration from invoice handlers
- [ ] 6.3 Create `backend/domain/services/conversation_service.py`
  - Extract: conversation persistence, reply chain logic, NL routing from conversation handlers
- [ ] 6.4 Create `backend/domain/services/admin_service.py`
  - Extract: admin reply routing, support draft management from admin handlers
- [ ] 6.5 Move module-level state (`_admin_reply_map`, `_support_draft_map`) into services or postgres repos
- [ ] 6.6 Write tests for new services
- [ ] 6.7 Run full test suite — all tests pass

---

## Phase 7: Clean up infrastructure leaks

> Goal: gateways are pure I/O wrappers, repos don't orchestrate.
> Rule: targeted fixes, one at a time.

- [ ] 7.1 Remove DB logging from `gemini_gateway.py` — make callers responsible for logging classifications
- [ ] 7.2 Move contractor folder logic from `drive_gateway.py` → `contractor_repo.py` or a service
- [ ] 7.3 Extract email parsing from `email_gateway._parse()` → utility function
- [ ] 7.4 Move `redirect_in_budget` / `unredirect_in_budget` orchestration from `budget_repo.py` → a budget service
- [ ] 7.5 Make `exchange_rate_gateway` a class (consistent with other gateways), or move to utils
- [ ] 7.6 Add error handling to `email_gateway.py` public methods (fetch_unread, mark_read, send_reply)
- [ ] 7.7 Extract shared Google service builder from sheets/drive/docs gateways
- [ ] 7.8 Run full test suite — all tests pass

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
