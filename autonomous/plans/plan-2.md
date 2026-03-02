# Plan 2 — Decision Tracking, Health/Code Commands, Natural Language Bot, Editor Tools

## Current State Summary

- **DB**: PostgreSQL with 2 tables: `email_threads`, `email_messages`. No migration framework — raw SQL in `db_gateway.py`.
- **LLM**: All via Gemini 2.5 Flash (7 use cases). No decision audit trail — all in-memory, lost on restart.
- **Email flow**: Inbox → classify (support/editorial/ignore) → LLM draft → admin approve/skip in Telegram → send/discard. Rejected drafts are **discarded** (popped from memory dict). Outbound replies saved to `email_messages`.
- **Bot**: Private 1:1 only. No groupchat support. Admin commands are stateless. No natural language classification.
- **Code/Claude**: `ANTHROPIC_API_KEY` exists in config, repo gateway exists, but no Claude subprocess integration yet.

---

## Phase 1: Email Decision Tracking (DB foundation)

### 1.1 New `email_decisions` table + CRUD in `db_gateway.py`

- [x] Add `email_decisions` table to `_SCHEMA_SQL`:
  ```sql
  CREATE TABLE IF NOT EXISTS email_decisions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMP DEFAULT NOW(),
      task TEXT NOT NULL,            -- 'SUPPORT_ANSWER', 'ARTICLE_APPROVAL'
      channel TEXT NOT NULL DEFAULT 'EMAIL',
      input_message_ids TEXT[] NOT NULL,
      output TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'PENDING',
      decided_by TEXT DEFAULT '',
      decided_at TIMESTAMP
  );
  ```
- [x] Add `create_email_decision(task, channel, input_message_ids, output) -> str` method
- [x] Add `update_email_decision(decision_id, status, decided_by=None)` method
- [x] Add `update_email_decision_output(decision_id, output)` method
- [x] Add `get_email_decision(decision_id) -> dict | None` method
- [x] Add `get_thread_message_ids(thread_id) -> list[str]` method

**Why `input_message_ids TEXT[]`**: email_messages already stores full body/from/subject, so we reconstruct full input by fetching messages by IDs. Avoids duplicating large email bodies.

**Files**: `backend/infrastructure/gateways/db_gateway.py`

### 1.2 Store rejected drafts in `email_messages`

Currently `skip_support()` pops from memory dict — the draft vanishes.

- [x] Change `TechSupportHandler.discard(uid)` to save the draft to `email_messages` with `direction='draft_rejected'` instead of just popping
- [x] Pass `DbGateway` and draft data needed for saving into `discard()`

**Files**: `backend/domain/tech_support_handler.py`

### 1.3 Wire decision tracking into `InboxService`

- [x] Add `DbGateway` dependency to `InboxService.__init__()`
- [x] In `_handle_support()`: after draft is created, create PENDING decision record, store `decision_id` on `SupportDraft`
- [x] In `_handle_editorial()`: after item is created, create PENDING decision record, store `decision_id` on `EditorialItem`
- [x] In `approve_support(uid)`: update decision to APPROVED
- [x] In `skip_support(uid)`: save rejected draft to email_messages, update decision to REJECTED
- [x] In `approve_editorial(uid)`: update decision to APPROVED
- [x] In `skip_editorial(uid)`: update decision to REJECTED

**Files**: `backend/domain/inbox_service.py`

### 1.4 Extend models with `decision_id`

- [x] Add `decision_id: str = ""` to `SupportDraft`
- [x] Add `decision_id: str = ""` to `EditorialItem`

**Files**: `common/models.py`

### 1.5 Tests for Phase 1

- [x] Test `email_decisions` CRUD in `test_db_gateway.py`
- [x] Test `get_thread_message_ids` in `test_db_gateway.py`
- [x] Test that `approve_support` creates APPROVED decision record
- [x] Test that `skip_support` creates REJECTED decision + saves draft to email_messages
- [x] Test that `approve_editorial` creates APPROVED decision record
- [x] Test that `skip_editorial` creates REJECTED decision record
- [x] Run full test suite, verify no regressions

**Files**: `tests/test_db_gateway.py` (extend), `tests/test_inbox_service.py` (new or extend `test_tech_support_handler.py`)

---

## Phase 2: /health, /tech_support, /code Commands

### 2.1 /health command

- [x] Add `HEALTHCHECK_DOMAINS` to `common/config.py` (from env, comma-separated, default `"republicmag.io,redefine.media"`)
- [x] Add `KUBECTL_ENABLED` bool to `common/config.py` (default `False`)
- [x] Create `backend/domain/healthcheck.py` with `HealthResult` dataclass (`name`, `status`, `details`)
- [x] Implement HTTP domain checks (`requests.get(url, timeout=5)`, catch exceptions)
- [x] Implement kubectl checks (`subprocess.run(["kubectl", ...], capture_output=True, timeout=10)`) gated by `KUBECTL_ENABLED`
- [x] Implement `run_healthchecks() -> list[HealthResult]`
- [x] Implement `format_healthcheck_results(results) -> str` for Telegram output
- [x] Add `cmd_health` handler in `flow_callbacks.py`
- [x] Register `/health` as `AdminCommand` in `flows.py`
- [x] Re-export from `backend/__init__.py`

**Files**: `backend/domain/healthcheck.py` (new), `telegram_bot/flow_callbacks.py`, `telegram_bot/flows.py`, `common/config.py`, `backend/__init__.py`

### 2.2 /tech_support command

- [x] Create `templates/tech-support-question.md` — takes question + knowledge + optional code context, instructs concise Telegram-friendly output
- [x] Add `tech_support_question(question, code_context="", verbose=False)` to `compose_request.py`
- [x] Add `cmd_tech_support` handler in `flow_callbacks.py`:
  - [x] Extract text after `/tech_support`
  - [x] Parse verbose flag (`-v` or `verbose` prefix)
  - [x] Optionally fetch code context from repos via `RepoGateway`
  - [x] Call Gemini, reply in Telegram
- [x] Register `/tech_support` as `AdminCommand` in `flows.py`

**Files**: `templates/tech-support-question.md` (new), `backend/domain/compose_request.py`, `telegram_bot/flow_callbacks.py`, `telegram_bot/flows.py`

### 2.3 /code command

- [x] Create `backend/domain/code_runner.py` with `run_claude_code(prompt, verbose=False) -> str`
  - [x] Use `subprocess.run(["claude", "-p", prompt, "--max-turns", "5"], capture_output=True, cwd=REPOS_DIR, timeout=300)`
  - [x] Prepend system instruction for concise Telegram output (omit if verbose)
  - [x] Truncate output to 4000 chars for Telegram
- [x] Add `cmd_code` handler in `flow_callbacks.py`:
  - [x] Extract text after `/code`
  - [x] Parse verbose flag
  - [x] Run in thread, reply with result
- [x] Register `/code` as `AdminCommand` in `flows.py`
- [x] Update `Dockerfile` to install Claude CLI (node + `@anthropic-ai/claude-code`)
- [x] Re-export from `backend/__init__.py`

**Files**: `backend/domain/code_runner.py` (new), `telegram_bot/flow_callbacks.py`, `telegram_bot/flows.py`, `Dockerfile`, `backend/__init__.py`

### 2.4 Remove code context from email tech support pipeline

- [x] Remove `_fetch_code_context()` call from `draft_reply()` in `TechSupportHandler`
- [x] Remove `code_context` variable and its inclusion in the LLM prompt within `draft_reply()`
- [x] Keep `_fetch_code_context()` method and `RepoGateway` intact (reused by /tech_support)

**Files**: `backend/domain/tech_support_handler.py`

### 2.5 Tests for Phase 2

- [x] Test `run_healthchecks()` with mocked HTTP responses (up/down scenarios)
- [x] Test `run_healthchecks()` with mocked kubectl subprocess
- [x] Test `format_healthcheck_results()` output formatting
- [x] Test `tech_support_question()` prompt composition
- [x] Test `run_claude_code()` with mocked subprocess (success + timeout + error)
- [x] Test verbose flag parsing for both commands
- [x] Test that `draft_reply()` no longer includes code context
- [x] Run full test suite, verify no regressions

**Files**: `tests/test_healthcheck.py` (new), `tests/test_code_runner.py` (new), `tests/test_compose_request.py` (extend), `tests/test_tech_support_handler.py` (extend)

---

## Phase 3: Natural Language Bot + Groupchat Support

### 3.1 Command classifier (Gemini-based)

- [x] Create `templates/classify-command.md` — input: user text + available commands with descriptions, output: `{"command": "..." | null, "args": "..."}`
- [x] Add `classify_command(text, commands_description)` to `compose_request.py`
- [x] Create `backend/domain/command_classifier.py`:
  - [x] `ClassifiedCommand` dataclass (`command: str`, `args: str`)
  - [x] `CommandClassifier.classify(text, available_commands) -> ClassifiedCommand | None`
- [x] Re-export from `backend/__init__.py`

**Files**: `templates/classify-command.md` (new), `backend/domain/compose_request.py`, `backend/domain/command_classifier.py` (new), `backend/__init__.py`

### 3.2 Groupchat configuration

- [x] Add `GroupChatConfig` dataclass to `flow_dsl.py` (`chat_id: int`, `allowed_commands: list[str]`, `natural_language: bool = True`)
- [x] Add `group_configs: list[GroupChatConfig]` to `BotFlows`
- [x] Add `EDITORIAL_CHAT_ID` to `common/config.py`
- [x] Add `BOT_USERNAME` to `common/config.py`
- [x] Define editorial groupchat config in `flows.py` with `allowed_commands=["health", "tech_support", "code"]`

**Files**: `telegram_bot/flow_dsl.py`, `telegram_bot/flows.py`, `common/config.py`

### 3.3 Groupchat message handler

- [x] Add bot mention detection helper: extract clean text, check if bot is @mentioned or replied to
- [x] Add group message handler in `flow_callbacks.py`:
  - [x] Check `message.chat.type` in `("group", "supergroup")`
  - [x] Find `GroupChatConfig` for `chat_id`, skip if not configured
  - [x] If explicit command: check if in `allowed_commands`, execute
  - [x] If mentions bot: run `CommandClassifier` with group's `allowed_commands`
  - [x] If classified: execute the command
  - [x] If not classified: ignore
- [x] Build command dispatch map (command name → handler function) for reuse

**Files**: `telegram_bot/flow_callbacks.py`

### 3.4 Register group handler in flow engine

- [x] Add group-aware router registration in `flow_engine.py`
- [x] Register group handler with appropriate filters (`F.chat.type.in_({"group", "supergroup"})`)
- [x] Ensure group handler does NOT interfere with existing private chat handlers
- [x] No changes to `main.py` needed — flow engine handles all registration

**Files**: `telegram_bot/flow_engine.py`, `telegram_bot/main.py`

### 3.5 Tests for Phase 3

- [x] Test `CommandClassifier` with Russian NL inputs (e.g. "у нас сайт лежит" → health)
- [x] Test `CommandClassifier` returns None for irrelevant messages
- [x] Test `GroupChatConfig` filtering (configured chat vs unconfigured)
- [x] Test mention extraction (strip @username, handle replies)
- [x] Test that group commands dispatch correctly
- [x] Run full test suite, verify no regressions

**Files**: `tests/test_command_classifier.py` (new), `tests/test_flow_engine.py` (extend)

---

## Phase 4: Editor-Useful Features

### 4.1 /articles command

- [x] Add `cmd_articles` handler in `flow_callbacks.py`:
  - [x] Parse args: `<author_name> [month]` (default: previous month)
  - [x] Fuzzy-find contractor by name
  - [x] Call `fetch_articles(contractor, month)`
  - [x] Format result: article count, list of article IDs, role
- [x] Register `/articles` as `AdminCommand` in `flows.py`
- [x] Add `"articles"` to editorial groupchat's `allowed_commands`

**Files**: `telegram_bot/flow_callbacks.py`, `telegram_bot/flows.py`

### 4.2 /lookup command

- [x] Add `cmd_lookup` handler in `flow_callbacks.py`:
  - [x] Parse args: `<name>`
  - [x] Fuzzy-find contractor
  - [x] Show: name, type, role, invoice status, payment data completeness
  - [x] Do NOT show sensitive fields (passport, bank account) — only presence/absence
- [x] Register `/lookup` as `AdminCommand` in `flows.py`
- [x] Add `"lookup"` to editorial groupchat's `allowed_commands`

**Files**: `telegram_bot/flow_callbacks.py`, `telegram_bot/flows.py`

### 4.3 Tests for Phase 4

- [x] Test `/articles` with mocked `fetch_articles`
- [x] Test `/articles` with unknown author
- [x] Test `/lookup` with mocked contractor data
- [x] Test `/lookup` does not expose sensitive fields
- [x] Run full test suite, verify no regressions

**Files**: `tests/test_flow_callbacks_helpers.py` (extend)

---

## Phase 5: LLM Decision Tracking

### 5.1 `llm_classifications` table (unified classifier logging)

- [x] Add table to `_SCHEMA_SQL`:
  ```sql
  CREATE TABLE IF NOT EXISTS llm_classifications (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMP DEFAULT NOW(),
      task TEXT NOT NULL,
      model TEXT NOT NULL,
      input_text TEXT NOT NULL,
      output_json TEXT NOT NULL,
      latency_ms INT DEFAULT 0
  );
  ```
- [x] Add `log_classification(task, model, input_text, output_json, latency_ms)` to `DbGateway`
- [x] Add optional `task` parameter to `GeminiGateway.call()`
- [x] When `task` is provided, measure latency and call `log_classification`
- [x] Update caller: `InboxService._llm_classify()` — pass `task="INBOX_CLASSIFY"`
- [x] Update caller: `InboxService._handle_editorial()` — pass `task="EDITORIAL_ASSESS"`
- [x] Update caller: `TechSupportHandler._fetch_user_data()` — pass `task="SUPPORT_TRIAGE"`
- [x] Update caller: `TechSupportHandler._fetch_code_context()` — pass `task="TECH_SEARCH_TERMS"`
- [x] Update caller: `CommandClassifier.classify()` — pass `task="COMMAND_CLASSIFY"`
- [x] Update caller: `compose_request.translate_name()` callsite — pass `task="TRANSLATE_NAME"`

**Files**: `backend/infrastructure/gateways/db_gateway.py`, `backend/infrastructure/gateways/gemini_gateway.py`, `backend/domain/inbox_service.py`, `backend/domain/tech_support_handler.py`, `backend/domain/command_classifier.py`

### 5.2 `payment_validations` table

- [x] Add table to `_SCHEMA_SQL`:
  ```sql
  CREATE TABLE IF NOT EXISTS payment_validations (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMP DEFAULT NOW(),
      contractor_id TEXT,
      contractor_type TEXT,
      input_text TEXT NOT NULL,
      parsed_json TEXT NOT NULL,
      validation_warnings TEXT[],
      is_final BOOLEAN DEFAULT FALSE
  );
  ```
- [x] Add `log_payment_validation(contractor_id, type, input, parsed, warnings, is_final)` to `DbGateway`
- [x] Call `log_payment_validation` from `_parse_with_llm()` in `flow_callbacks.py`
- [x] Set `is_final=True` when `_finish_registration()` completes successfully

**Files**: `backend/infrastructure/gateways/db_gateway.py`, `telegram_bot/flow_callbacks.py`

### 5.3 `code_tasks` table + rating

- [x] Add table to `_SCHEMA_SQL`:
  ```sql
  CREATE TABLE IF NOT EXISTS code_tasks (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMP DEFAULT NOW(),
      requested_by TEXT,
      input_text TEXT NOT NULL,
      output_text TEXT NOT NULL,
      verbose BOOLEAN DEFAULT FALSE,
      rating INT,
      rated_at TIMESTAMP
  );
  ```
- [x] Add `create_code_task(requested_by, input, output, verbose) -> str` to `DbGateway`
- [x] Add `rate_code_task(task_id, rating)` to `DbGateway`
- [x] Save task in `cmd_code` handler after Claude returns
- [x] Show rating buttons (1-5) as inline keyboard after response
- [x] Add `handle_code_rate_callback` for `code_rate:<id>:<rating>` prefix
- [x] Register callback in `main.py`

**Files**: `backend/infrastructure/gateways/db_gateway.py`, `backend/domain/code_runner.py`, `telegram_bot/flow_callbacks.py`, `telegram_bot/main.py`

### 5.4 Tests for Phase 5

- [x] Test `log_classification` writes correct data
- [x] Test `GeminiGateway.call()` with `task` param logs to DB
- [x] Test `GeminiGateway.call()` without `task` param does NOT log
- [x] Test `log_payment_validation` writes correct data
- [x] Test `create_code_task` and `rate_code_task` CRUD
- [x] Test code rating callback handler
- [x] Run full test suite, verify no regressions

**Files**: `tests/test_db_gateway.py` (extend), `tests/test_gemini_gateway.py` (new or extend), `tests/test_code_runner.py` (extend)

---

## Phase 6: Domain Structure for LLM Decisions (Future Ambition)

> **Prerequisite**: All phases 1-5 complete and passing tests. This is optional/stretch.
>
> **Evaluation (Session 11)**: Deferred. After analyzing the current LLM code patterns (compose → gemini.call → extract), the proposed class hierarchy (LLMTask protocol + 3 base classes + tracker + 9 subclasses) would add ~14 files of indirection without changing behavior. The current pattern is clean and consistent. Each LLM category is already tracked in its own table (llm_classifications, email_decisions, payment_validations, code_tasks). This conflicts with the project's "clean & minimalistic" philosophy and "don't create abstractions for one-time operations" principle. Revisit only if a concrete need emerges (e.g., adding a new LLM provider, needing unified retry logic).

### 6.1 Analysis of LLM decision landscape

After phases 1-5, we have these tables:
- `email_decisions` — human decisions on LLM-drafted emails
- `llm_classifications` — all LLM classifier outputs
- `payment_validations` — LLM-parsed payment data + validation results
- `code_tasks` — Claude Code tasks + ratings

LLM use cases fall into 3 categories:

**A. Classifiers** (text in → category out): inbox_classify, editorial_assess, support_triage, classify_command — unified in `llm_classifications`

**B. Generators** (input → natural language output): support_email, tech_support_question, code_task — tracked in `email_decisions` / `code_tasks`

**C. Extractors** (text → structured data): contractor_parse, translate_name, tech_search_terms — tracked in `payment_validations` / `llm_classifications`

### 6.2 Create `backend/domain/llm/` package

- [ ] Create `backend/domain/llm/__init__.py`
- [ ] Create `backend/domain/llm/base.py` with `LLMTask` protocol and `LLMResult` model
- [ ] Create `backend/domain/llm/classifier.py` — `ClassifierTask` base
- [ ] Create `backend/domain/llm/generator.py` — `GeneratorTask` base
- [ ] Create `backend/domain/llm/extractor.py` — `ExtractorTask` base
- [ ] Create `backend/domain/llm/tracker.py` — `LLMTracker` (routes to correct table by category)

### 6.3 Migrate one classifier as proof of concept

- [ ] Migrate `inbox_classify` to `ClassifierTask` subclass
- [ ] Verify existing tests still pass
- [ ] Verify behavior is identical

### 6.4 Migrate remaining use cases (if 6.3 succeeds)

- [ ] Migrate remaining classifiers: editorial_assess, support_triage, classify_command
- [ ] Migrate generators: support_email, tech_support_question
- [ ] Migrate extractors: contractor_parse, translate_name, tech_search_terms
- [ ] Update or deprecate `compose_request.py` in favor of task classes
- [ ] Run full test suite after each migration

**Files**: `backend/domain/llm/` (new package), various domain files

---

## Implementation Order & Dependencies

```
Phase 1 (DB foundation)     ← do first, all others depend on it
  ↓
Phase 2 (commands)           ← independent of Phase 3
  ↓
Phase 3 (NL + groupchat)    ← depends on Phase 2 commands existing
  ↓
Phase 4 (editor features)   ← depends on Phase 3 groupchat support
  ↓
Phase 5 (LLM tracking)      ← can be done in parallel with Phase 3/4
  ↓
Phase 6 (domain refactor)   ← only after everything else passes
```

## New Files Summary

| File | Phase | Purpose |
|------|-------|---------|
| `backend/domain/healthcheck.py` | 2 | Domain/k8s healthchecks |
| `backend/domain/code_runner.py` | 2 | Claude Code subprocess runner |
| `backend/domain/command_classifier.py` | 3 | NL → command classification |
| `templates/tech-support-question.md` | 2 | LLM prompt for /tech_support |
| `templates/classify-command.md` | 3 | LLM prompt for NL classification |
| `tests/test_healthcheck.py` | 2 | Healthcheck tests |
| `tests/test_code_runner.py` | 2 | Code runner tests |
| `tests/test_command_classifier.py` | 3 | Classifier tests |
| `tests/test_inbox_service.py` | 1 | Decision tracking tests |
| `backend/domain/llm/` | 6 | LLM task abstractions (future) |

## Modified Files Summary

| File | Phases | Changes |
|------|--------|---------|
| `backend/infrastructure/gateways/db_gateway.py` | 1,5 | New tables + CRUD methods |
| `backend/domain/inbox_service.py` | 1 | Decision tracking on approve/skip |
| `backend/domain/tech_support_handler.py` | 1,2 | Save rejected drafts, remove code context from email |
| `common/models.py` | 1 | decision_id on SupportDraft/EditorialItem |
| `telegram_bot/flow_callbacks.py` | 2,3,4,5 | New command handlers, NL handler, rating |
| `telegram_bot/flows.py` | 2,3,4 | New commands, group configs |
| `telegram_bot/flow_dsl.py` | 3 | GroupChatConfig dataclass |
| `telegram_bot/flow_engine.py` | 3 | Group message routing |
| `telegram_bot/main.py` | 3,5 | New callback registrations |
| `backend/domain/compose_request.py` | 2,3 | New prompt composers |
| `backend/infrastructure/gateways/gemini_gateway.py` | 5 | Classification logging |
| `common/config.py` | 2,3 | New env vars |
| `Dockerfile` | 2 | Claude CLI installation |
| `backend/__init__.py` | 2,3,4 | Re-exports |

## New Env Vars

```bash
# Phase 2
HEALTHCHECK_DOMAINS=republicmag.io,redefine.media
KUBECTL_ENABLED=true

# Phase 3
EDITORIAL_CHAT_ID=-100123456789
BOT_USERNAME=your_bot_username
```

## Risk Assessment

- **Phase 1**: Low — extends existing DB pattern, straightforward CRUD
- **Phase 2**: Medium — /code depends on Claude CLI in Docker, subprocess management
- **Phase 3**: Medium — groupchat handling is new territory, NL classification accuracy
- **Phase 4**: Low — reuses existing backend functions
- **Phase 5**: Low — logging/tracking, no behavior changes
- **Phase 6**: Medium — refactoring risk, but optional and incremental
