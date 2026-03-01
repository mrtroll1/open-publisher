# Implementation Plan — 6 Features for Republic Agent

## Codebase Summary (Current State)

**Project structure:**
- `common/` — shared config, models (Pydantic), prompt loader
- `backend/` — domain use cases + infrastructure (gateways + repositories)
- `telegram_bot/` — aiogram 3 bot with declarative flow DSL
- `templates/` — LLM prompt templates (Markdown with `{{placeholders}}`)
- `knowledge/` — knowledge base files for LLM context
- `config/` — `.env`, `business_config.json`, `tech_config.json`, `service_account.json`
- `autonomous/` — autonomous Claude Code runner scripts
- `docs/` — deploy scripts, sample data

**Key patterns:**
- Declarative flow DSL: flows defined in `flows.py` as dataclasses, wired by `flow_engine.py`
- Handler functions in `flow_callbacks.py` return `str | None` to drive transitions
- Backend facade in `backend/__init__.py` re-exports everything the bot needs
- Google Sheets is the primary persistence layer (contractors, invoices, budget, rules)
- Gmail API for email (polling-based)
- Gemini (gemini-2.5-flash) as the LLM for all AI tasks
- `compose_request.py` assembles LLM prompts from templates + knowledge files

**How users are identified:**
- Contractors stored in Google Sheets with `telegram` column = Telegram user ID
- `find_contractor_by_telegram_id()` checks if a user is already linked
- Admins identified by `ADMIN_TELEGRAM_IDS` env var
- Editors identified by `role_code` field on `Contractor` model (`R` = Redaktor)

---

## Phase 1: Foundation (Features 6 + 1)

### Feature 6: Postgres + Email Thread Tracking

**Why first:** Establishes database infrastructure all other features may benefit from.

#### Step 6.1: Add Postgres to docker-compose.yml
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    restart: unless-stopped
    environment:
      POSTGRES_DB: republic_agent
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: ${DB_PASSWORD:-agent_dev_pass}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  bot:
    depends_on:
      - db

volumes:
  pgdata:
```

#### Step 6.2: Add env var
`common/config.py`:
```python
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://agent:agent_dev_pass@db:5432/republic_agent")
```

#### Step 6.3: Create `backend/infrastructure/gateways/db_gateway.py`
New file with:
- Schema: `email_threads` table (thread_id PK, subject, created_at) + `email_messages` table (id, thread_id FK, message_id UNIQUE, in_reply_to, from_addr, to_addr, subject, body, date, direction, created_at)
- `DbGateway` class with methods:
  - `init_schema()` — runs CREATE TABLE IF NOT EXISTS
  - `find_thread(message_id, in_reply_to, subject)` — finds existing thread by in_reply_to or normalized subject, or creates new one
  - `save_message(thread_id, email, direction)` — inserts message into `email_messages`
  - `get_thread_history(thread_id, limit=10)` — returns ordered messages in thread

#### Step 6.4: Add `in_reply_to` and `references` to IncomingEmail
`common/models.py`:
```python
class IncomingEmail(BaseModel):
    ...
    in_reply_to: str = ""   # NEW
    references: str = ""    # NEW
```

#### Step 6.5: Parse In-Reply-To and References headers
`backend/infrastructure/gateways/email_gateway.py` — in `_parse` method, extract these headers and pass to `IncomingEmail` constructor.

#### Step 6.6: Integrate thread tracking into SupportEmailService
`backend/domain/support_email_service.py`:
- Init `DbGateway` in constructor, call `init_schema()`
- In `_draft()`: find/create thread, save inbound message, get thread history, format as context, include in LLM prompt
- In `approve()`: save outbound reply to thread
- Add `_format_thread(history)` static method to format history for LLM

#### Step 6.7: Add `psycopg2-binary` to `requirements.txt`

**Files to create:** `backend/infrastructure/gateways/db_gateway.py`
**Files to modify:** `docker-compose.yml`, `common/config.py`, `common/models.py`, `backend/infrastructure/gateways/email_gateway.py`, `backend/domain/support_email_service.py`, `requirements.txt`, `config/example/.env`

---

### Feature 1: Linked User Menu

#### Step 1.1: Add reply strings
`telegram_bot/replies.py` — new class `linked_menu`:
```python
class linked_menu:
    prompt = "Здравствуйте, {name}! Что вы хотите сделать?"
    btn_contract = "Подписать договор для выплат"
    btn_update = "Обновить мои платежные данные"
    btn_editor_sources = "Настроить, за кого я получаю деньги"  # Feature 2
    update_prompt = "Какие данные вы хотите обновить? Отправьте новые значения в свободной форме."
    update_success = "Данные обновлены."
    no_changes = "Изменений не найдено."
```

#### Step 1.2: Add FSM states for update flow
`telegram_bot/flows.py` — add to contractor flow:
- `waiting_update_choice` — shows field selection buttons + "update all"
- `waiting_update_data` — accepts free-form text, parses with LLM, updates sheet

#### Step 1.3: Modify `handle_contractor_text`
`telegram_bot/flow_callbacks.py`:
- When a bound contractor is found, show the menu with inline buttons instead of immediately delivering invoices
- `menu:contract` → existing `_deliver_existing_invoice` logic
- `menu:update` → enters update FSM state

#### Step 1.4: Add `handle_linked_menu_callback`
`telegram_bot/flow_callbacks.py` — new callback handler for `menu:` prefix:
- `menu:contract` → deliver invoice
- `menu:update` → prompt for updated data
- `menu:editor` → Feature 2

#### Step 1.5: Add `update_contractor_fields()`
`backend/infrastructure/repositories/contractor_repo.py`:
- Takes contractor ID + dict of field→value updates
- Finds row in correct sheet, writes updated values to correct cells

#### Step 1.6: Register callbacks
`telegram_bot/main.py`:
```python
dp.callback_query.register(handle_linked_menu_callback, F.data.startswith("menu:"))
```

#### Step 1.7: Modify `handle_start` for linked users
Show menu for linked contractors instead of generic greeting.

**Files to modify:** `telegram_bot/replies.py`, `telegram_bot/flows.py`, `telegram_bot/flow_callbacks.py`, `telegram_bot/main.py`, `backend/infrastructure/repositories/contractor_repo.py`, `backend/__init__.py`

---

## Phase 2: Editor Tools (Feature 2)

### Feature 2: Editor Source Management

#### Step 2.1: Add CRUD to rules_repo
`backend/infrastructure/repositories/rules_repo.py`:
```python
def find_redirect_rules_by_target(target_id: str) -> list[RedirectRule]:
    """Find all redirect rules where the given contractor is the target."""

def add_redirect_rule(source_name: str, target_id: str, add_to_total: bool = True) -> None:
    """Append a new redirect rule row to the sheet."""

def remove_redirect_rule(source_name: str, target_id: str) -> bool:
    """Remove a redirect rule by clearing the row. Returns True if found."""
```

#### Step 2.2: Modify the linked user menu
In the menu construction (Feature 1), check `contractor.role_code == RoleCode.REDAKTOR`. If editor, add button `menu:editor` → "Настроить, за кого я получаю деньги".

#### Step 2.3: Add editor source handlers
`telegram_bot/flow_callbacks.py`:
- `handle_editor_source_callback` for `esrc:` prefix:
  - `esrc:list` → shows current sources with remove buttons
  - `esrc:rm:{source_name}` → removes redirect rule, refreshes list
  - `esrc:add` → enters text input state

#### Step 2.4: Add FSM state for new source
`telegram_bot/flows.py`:
- `waiting_editor_source_name` — text input, validates name exists in budget table, calls `add_redirect_rule`

#### Step 2.5: Add reply strings
`telegram_bot/replies.py`:
```python
class editor_sources:
    header = "Сейчас вы получаете деньги за:"
    empty = "У вас пока нет привязанных авторов."
    removed = "Автор {name} удалён из списка."
    add_prompt = "Введите имя автора (как в бюджетной таблице):"
    not_found = "Автор «{name}» не найден в бюджетной таблице."
    added = "Автор {name} добавлен."
    btn_add = "Добавить автора"
    btn_back = "Назад"
```

#### Step 2.6: Register callbacks
`telegram_bot/main.py`:
```python
dp.callback_query.register(handle_editor_source_callback, F.data.startswith("esrc:"))
```

**Files to modify:** `backend/infrastructure/repositories/rules_repo.py`, `backend/__init__.py`, `telegram_bot/flow_callbacks.py`, `telegram_bot/flows.py`, `telegram_bot/replies.py`, `telegram_bot/main.py`

---

## Phase 3: Data Pipeline (Feature 3)

### Feature 3: Redefine PNL + Exchange Rate → Budget Sheet

#### Step 3.1: Add env vars
`common/config.py`:
```python
PNL_API_URL = os.getenv("PNL_API_URL", "")
PNL_API_USER = os.getenv("PNL_API_USER", "")
PNL_API_PASSWORD = os.getenv("PNL_API_PASSWORD", "")
EUR_RUB_CELL = os.getenv("EUR_RUB_CELL", "G2")
```

#### Step 3.2: Add PNL method to RedefineGateway
`backend/infrastructure/gateways/redefine_gateway.py`:
```python
def get_pnl_stats(self, month: str) -> dict:
    """Fetch PNL statistics from Redefine API for a given month."""
    resp = requests.get(
        f"{PNL_API_URL}/stats",
        params={"month": month},
        auth=(PNL_API_USER, PNL_API_PASSWORD),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})
```

#### Step 3.3: Create exchange rate gateway
New file `backend/infrastructure/gateways/exchange_rate_gateway.py`:
```python
def fetch_eur_rub_rate() -> float:
    """Fetch current EUR/RUB exchange rate from a public API."""
```

#### Step 3.4: Modify budget generation
`backend/domain/compute_budget.py`:
- After populating budget sheet, fetch PNL data from Redefine
- Fetch EUR/RUB rate and write to designated cell (e.g. `G2`)
- Write PNL rows with formulas: `=ROUND(123456/$G$2, 0)` for EUR conversion
- Use `USER_ENTERED` value input option so Google Sheets interprets formulas

#### Step 3.5: Modify budget_repo.py
`backend/infrastructure/repositories/budget_repo.py`:
- Add parameter for EUR/RUB rate
- Write rate to designated cell
- Support formula cells in PNL rows

**Files to create:** `backend/infrastructure/gateways/exchange_rate_gateway.py`
**Files to modify:** `common/config.py`, `backend/infrastructure/gateways/redefine_gateway.py`, `backend/domain/compute_budget.py`, `backend/infrastructure/repositories/budget_repo.py`, `backend/__init__.py`, `config/example/.env`

---

## Phase 4: Email Intelligence (Features 4 + 5)

### Feature 4: Article Proposal Monitoring

#### Step 4.1: Add env var
`common/config.py`:
```python
CHIEF_EDITOR_EMAIL = os.getenv("CHIEF_EDITOR_EMAIL", "")
```

#### Step 4.2: Create ArticleProposalService
New file `backend/domain/article_proposal_service.py`:
- `process_non_support_emails(emails)` — filters non-support emails, triages each
- `_judge_proposal(email)` — LLM judges if email is a legit article proposal
- `forward_to_chief_editor(email)` — forwards via EmailGateway

#### Step 4.3: Create LLM prompt
New file `templates/article-proposal-triage.md`:
- Input: email text
- Output: `{"is_legit_proposal": true/false, "reason": "..."}`

#### Step 4.4: Add compose function
`backend/domain/compose_request.py`:
```python
def article_proposal_triage(email_text: str) -> tuple[str, str, list[str]]:
```

#### Step 4.5: Modify email_listener_task
`telegram_bot/flow_callbacks.py`:
- After fetching unread emails, split into support vs non-support
- Non-support: run proposal triage, forward legit ones, skip others
- Notify admin about forwarded proposals

#### Step 4.6: Expose non-support emails from SupportEmailService
`backend/domain/support_email_service.py`:
- Add method or modify `fetch_new_drafts` to also return/expose skipped (non-support) emails

**Files to create:** `backend/domain/article_proposal_service.py`, `templates/article-proposal-triage.md`
**Files to modify:** `common/config.py`, `backend/domain/compose_request.py`, `telegram_bot/flow_callbacks.py`, `backend/domain/support_email_service.py`, `backend/__init__.py`, `config/example/.env`

---

### Feature 5: Repo Access for Tech Support

#### Step 5.1: Add env vars
`common/config.py`:
```python
REPOS_DIR = os.getenv("REPOS_DIR", "/opt/repos")
REPUBLIC_REPO_URL = os.getenv("REPUBLIC_REPO_URL", "")
REDEFINE_REPO_URL = os.getenv("REDEFINE_REPO_URL", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
```

#### Step 5.2: Create RepoGateway
New file `backend/infrastructure/gateways/repo_gateway.py`:
- `ensure_repos()` — clone or pull all repos
- `search_code(query, repo=None)` — grep-based search across repos
- `read_file(repo, filepath, max_lines=200)` — read a file from a repo

#### Step 5.3: Create LLM prompt for search terms
New file `templates/tech-search-terms.md`:
- Input: support email text
- Output: `{"search_terms": [...], "needs_code": true/false}`

#### Step 5.4: Integrate into SupportEmailService
`backend/domain/support_email_service.py`:
- Add `_fetch_code_context(email_text)`:
  - Use LLM to extract search terms
  - Search repos via RepoGateway
  - Read relevant file snippets
  - Return formatted code context
- Include code context in the LLM prompt for support email drafts

#### Step 5.5: Modify Docker setup
- `Dockerfile`: add `git` (`RUN apt-get update && apt-get install -y git`)
- `docker-compose.yml`: add repos volume (`- ./repos:/opt/repos`)

#### Step 5.6: Future — Claude Code subprocess (Option B, TODO)
Spawn `claude -p "..." --max-turns 5` as subprocess with repos dir as CWD. Requires Anthropic API key + Claude CLI in Docker. Not for v1.

**Files to create:** `backend/infrastructure/gateways/repo_gateway.py`, `templates/tech-search-terms.md`
**Files to modify:** `common/config.py`, `backend/domain/support_email_service.py`, `backend/domain/compose_request.py`, `Dockerfile`, `docker-compose.yml`, `config/example/.env`

---

## New Env Vars Summary

```bash
# Feature 3: PNL
PNL_API_URL=https://...
PNL_API_USER=...
PNL_API_PASSWORD=...

# Feature 4: Article proposals
CHIEF_EDITOR_EMAIL=chief-editor@gmail.com

# Feature 5: Repos
REPOS_DIR=/opt/repos
REPUBLIC_REPO_URL=https://gitlab.com/...
REDEFINE_REPO_URL=https://gitlab.com/...
ANTHROPIC_API_KEY=...

# Feature 6: Database
DATABASE_URL=postgresql://agent:agent_dev_pass@db:5432/republic_agent
DB_PASSWORD=agent_dev_pass
```

## New Files Summary

| File | Feature | Purpose |
|------|---------|---------|
| `backend/infrastructure/gateways/db_gateway.py` | 6 | PostgreSQL gateway for thread tracking |
| `backend/infrastructure/gateways/exchange_rate_gateway.py` | 3 | Fetch EUR/RUB rate |
| `backend/domain/article_proposal_service.py` | 4 | Judge and forward article proposals |
| `templates/article-proposal-triage.md` | 4 | LLM prompt for proposal classification |
| `backend/infrastructure/gateways/repo_gateway.py` | 5 | Clone, pull, search git repos |
| `templates/tech-search-terms.md` | 5 | LLM prompt to extract search terms |

## Risk Assessment

- **Feature 1**: Low risk — straightforward extension of existing patterns
- **Feature 2**: Low risk — builds on Feature 1 and existing rules_repo
- **Feature 3**: Medium risk — depends on Redefine PNL API existing; formula insertion is well-supported via `USER_ENTERED`
- **Feature 4**: Low risk — extends existing email infrastructure
- **Feature 5**: High risk — but doable:)
- **Feature 6**: Medium risk — new infra, but simple schema
