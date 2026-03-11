# Plan 13: Contractor Operations Overhaul

> Improve contractor matching, support stub contractors and type changes, add contractor lookup to the redirect flow, and give editors/admins natural language contractor operations via a new `contractors` Brain tool in the `editor_dm` environment.

## Architecture Overview

Five interconnected features sharing a common dependency: improved fuzzy matching in `contractor_repo.py`. Phase 1 improves the matching algorithm (word-order-independent, lower threshold). Phase 2 adds a "stub" Google Sheet tab and `StubContractor` model for typeless contractors that can later be claimed. Phase 3 adds contractor-type-change logic (delete from old sheet, create in new). Phase 4 wires contractor lookup + stub creation into the editor redirect source flow. Phase 5 creates the new `editor_dm` environment and a conversational `contractors` Brain tool, plus adjusts bot routing so admin/editor DMs can go through NL. All new CRUD for article rate rules goes into `rules_repo.py`. Tests follow `test_interact.py` patterns: mock repos, test handler/tool responses.

---

## Phase 1 — Improved Fuzzy Matching

### 1.1 Add word-order-independent matching to `fuzzy_find`

**File:** `src/backend/infrastructure/repositories/sheets/contractor_repo.py`

Add two helpers before `fuzzy_find`:

```python
def _normalize_words(text: str) -> set[str]:
    """Split into lowercase words."""
    return {w.strip() for w in text.lower().split() if w.strip()}


def _word_independent_score(query: str, name: str) -> float:
    """Score based on word overlap regardless of order."""
    q_words = _normalize_words(query)
    n_words = _normalize_words(name)
    if not q_words or not n_words:
        return 0.0
    overlap = q_words & n_words
    if not overlap:
        return 0.0
    return len(overlap) / max(len(q_words), len(n_words))
```

Modify the inner loop of `fuzzy_find` to also check word-independent score:

```python
for name in c.all_names:
    name_lower = name.lower().strip()
    if query_lower in name_lower or name_lower in query_lower:
        score = 0.95
    else:
        seq_score = _similarity(query_lower, name_lower)
        word_score = _word_independent_score(query_lower, name_lower)
        score = max(seq_score, word_score)
    best_score = max(best_score, score)
```

**Done when:**
- [x] `fuzzy_find("Иванов Петр", [...])` matches contractor named "Петр Иванов" with score >= 0.8
- [x] `fuzzy_find("John Smith", [...])` matches "Smith John" with score >= 0.8
- [x] Existing substring matching and SequenceMatcher still work

---

### 1.2 Lower self-registration suggestion threshold

**File:** `src/backend/interact/contractor.py`

In `free_text` method (line ~107), change:
```python
matches = fuzzy_find(query, contractors, threshold=0.8)
```
to:
```python
matches = fuzzy_find(query, contractors, threshold=0.6)
```

**Done when:**
- [x] `free_text` with a loose match (score 0.65) shows suggestions instead of starting registration
- [x] Very poor matches (score < 0.6) still go to registration

---

## Phase 2 — Stub Contractors

### 2.1 Add `StubContractor` model

**File:** `src/backend/models.py`

Add `STUB = "stub"` to `ContractorType` enum.

Add `is_stub` property to base `Contractor` class:
```python
@property
def is_stub(self) -> bool:
    return False
```

Add new class after `SamozanyatyContractor`:

```python
class StubContractor(Contractor):
    """Stub — name-only placeholder, no type yet, cannot receive invoices."""
    name: str

    SHEET_COLUMNS: ClassVar[list[str]] = [
        "id", "name", "aliases", "role_code",
        "telegram", "secret_code",
    ]

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        "name": FieldMeta("имя", required=True),
    }

    @property
    def type(self) -> ContractorType:
        return ContractorType.STUB

    @property
    def currency(self) -> Currency:
        raise NotImplementedError("Stub has no currency")

    @property
    def display_name(self) -> str:
        return self.name or self.id

    @property
    def all_names(self) -> list[str]:
        names = []
        if self.name:
            names.append(self.name)
        names.extend(self.aliases)
        return names

    @property
    def is_stub(self) -> bool:
        return True
```

Update `AnyContractor`:
```python
AnyContractor = GlobalContractor | IPContractor | SamozanyatyContractor | StubContractor
```

Do NOT add `StubContractor` to `CONTRACTOR_CLASS_BY_TYPE` — stubs are created/loaded separately.

**Done when:**
- [x] `StubContractor(id="c099", name="Test", aliases=[], role_code=RoleCode.AUTHOR, email="", bank_name="", bank_account="", telegram="", secret_code="abc")` creates successfully
- [x] `StubContractor.is_stub` returns `True`, `GlobalContractor.is_stub` returns `False`

---

### 2.2 Add stub sheet support to `contractor_repo.py`

**File:** `src/backend/infrastructure/repositories/sheets/contractor_repo.py`

Import `StubContractor` from models.

Add constant:
```python
STUB_SHEET = "stub"
```

Add `_parse_stub`:
```python
def _parse_stub(row: dict[str, str]) -> StubContractor | None:
    try:
        role_code, _ = _parse_role(row.get("role_code", "A"))
        return StubContractor(
            id=row.get("id", ""),
            name=row.get("name", ""),
            aliases=_parse_aliases(row.get("aliases", "")),
            role_code=role_code,
            email="", bank_name="", bank_account="",
            telegram=row.get("telegram", ""),
            secret_code=row.get("secret_code", ""),
        )
    except ValidationError as e:
        logger.warning("Skipping stub %s: %s", row.get("id", "???"), e)
        return None
```

Modify `load_all_contractors` to also load stubs:
```python
def load_all_contractors() -> list[Contractor]:
    contractors: list[Contractor] = []
    for sheet_name, (ctype, _currency) in SHEET_CONFIG.items():
        rows = _sheets.read_as_dicts(CONTRACTORS_SHEET_ID, _sheet_range(sheet_name))
        for r in rows:
            if r.get("id"):
                c = _parse_contractor(r, ctype)
                if c is not None:
                    contractors.append(c)
    # Stubs
    rows = _sheets.read_as_dicts(CONTRACTORS_SHEET_ID, _sheet_range(STUB_SHEET))
    for r in rows:
        if r.get("id"):
            c = _parse_stub(r)
            if c is not None:
                contractors.append(c)
    return contractors
```

Add `save_stub`:
```python
def save_stub(c: StubContractor) -> None:
    """Append a stub contractor to the stub sheet."""
    row = [getattr(c, col, "") if col != "aliases" else ", ".join(c.aliases)
           for col in StubContractor.SHEET_COLUMNS]
    _sheets.append(CONTRACTORS_SHEET_ID, _sheet_range(STUB_SHEET), [row])
    logger.info("Saved stub %s (%s) to stub sheet", c.id, c.display_name)
```

Add `delete_contractor_from_sheet` (needed for stub claiming + type change):
```python
def delete_contractor_from_sheet(contractor_id: str) -> bool:
    """Delete a contractor row from whichever sheet they're on. Returns True if found."""
    all_sheets = list(SHEET_CONFIG.keys()) + [STUB_SHEET]
    for sheet_name in all_sheets:
        rows = _sheets.read(CONTRACTORS_SHEET_ID, _sheet_range(sheet_name))
        if not rows:
            continue
        for idx, row in enumerate(rows[1:], start=1):
            if len(row) > 0 and row[0] == contractor_id:
                _sheets.delete_row(CONTRACTORS_SHEET_ID, sheet_name, idx)
                logger.info("Deleted %s from sheet '%s'", contractor_id, sheet_name)
                return True
    return False
```

**Google Sheet "stub" tab columns (header row):**
```
id | name | aliases | role_code | telegram | secret_code
```

**Done when:**
- [x] `load_all_contractors()` includes stubs
- [x] `save_stub(stub)` appends to stub sheet
- [x] `delete_contractor_from_sheet(id)` removes from correct sheet (typed or stub)
- [x] `fuzzy_find` works on stubs since they have `all_names`

---

### 2.3 Add `create_stub` to `ContractorFactory`

**File:** `src/backend/commands/contractor/create.py`

Add method:
```python
def create_stub(self, name: str, contractors: list) -> tuple:
    """Create a name-only stub contractor. Returns (StubContractor, secret_code)."""
    from backend.infrastructure.repositories.sheets.contractor_repo import (
        next_contractor_id, pop_random_secret_code, save_stub,
    )
    from backend.models import RoleCode, StubContractor
    cid = next_contractor_id(contractors)
    code = pop_random_secret_code()
    stub = StubContractor(
        id=cid, name=name, aliases=[name],
        role_code=RoleCode.AUTHOR,
        email="", bank_name="", bank_account="",
        telegram="", secret_code=code,
    )
    save_stub(stub)
    return stub, code
```

**Done when:**
- [x] `ContractorFactory().create_stub("Test Author", contractors)` saves to stub sheet, returns `(StubContractor, secret_code)`

---

### 2.4 Stub contractor claiming flow

**File:** `src/backend/interact/contractor.py`

When a stub contractor passes verification, transition to type selection + data entry instead of menu.

Modify `_bind_contractor`:
```python
def _bind_contractor(self, contractor, ctx):
    bind_telegram_id(contractor.id, ctx["user_id"])
    sides = [side_msg(admin_id,
                      text=f"Контрагент {contractor.display_name} привязался к Telegram.")
             for admin_id in ctx.get("admin_ids", [])]
    if contractor.is_stub:
        return respond([
            msg(f"Отлично! Вы привязаны как {contractor.display_name}."),
            msg("Теперь нужно выбрать тип и заполнить данные."),
            self._type_selection_prompt(),
        ], side_messages=sides, fsm_state="waiting_type",
           fsm_data={"alias": contractor.display_name,
                     "claiming_stub_id": contractor.id})
    return respond([
        msg(f"Отлично! Вы привязаны как {contractor.display_name}."),
        msg("Что хотите сделать?", keyboard=self._menu_keyboard(contractor)),
    ], side_messages=sides, fsm_state=None)
```

In `_complete_registration`, handle `claiming_stub_id`:
```python
def _complete_registration(self, collected, ctype, cls, raw_text, ctx):
    self._maybe_add_russian_alias(collected, ctype)
    telegram_id = str(ctx["user_id"])
    contractors = load_all_contractors()
    fsm_data = ctx.get("fsm_data", {})
    claiming_stub_id = fsm_data.get("claiming_stub_id")
    if claiming_stub_id:
        contractor, secret_code = self._upgrade_stub(
            claiming_stub_id, collected, ctype, telegram_id, contractors)
    else:
        contractor, secret_code = ContractorFactory().create(
            collected, ctype, telegram_id, contractors)
    sides = self._admin_registration_notify(collected, ctype, raw_text, ctx.get("admin_ids", []))
    messages = [self._registration_complete_msg(cls, collected, secret_code)]
    return self._try_invoice_after_registration(contractor, messages, sides)
```

Add `_upgrade_stub`:
```python
def _upgrade_stub(self, stub_id, collected, ctype, telegram_id, contractors):
    """Delete stub, create full contractor preserving id and secret_code."""
    from backend.infrastructure.repositories.sheets.contractor_repo import (
        delete_contractor_from_sheet, save_contractor,
    )
    stub = find_contractor_by_id(stub_id, contractors)
    secret_code = stub.secret_code if stub else ""
    delete_contractor_from_sheet(stub_id)
    # Build full contractor with stub's id and secret_code
    collected["aliases"] = collected.get("aliases", [])
    if stub and stub.display_name not in collected["aliases"]:
        collected["aliases"].append(stub.display_name)
    cls = CONTRACTOR_CLASS_BY_TYPE[ctype]
    kwargs = {
        "id": stub_id,
        "aliases": collected.get("aliases", []),
        "role_code": stub.role_code if stub else RoleCode.AUTHOR,
        "email": collected.get("email", ""),
        "bank_name": collected.get("bank_name", ""),
        "bank_account": collected.get("bank_account", ""),
        "mags": "",
        "invoice_number": 0,
        "telegram": telegram_id,
        "secret_code": secret_code,
    }
    for field in cls.FIELD_META:
        if field not in kwargs:
            kwargs[field] = collected.get(field, "")
    contractor = cls(**kwargs)
    save_contractor(contractor)
    return contractor, secret_code
```

**Done when:**
- [x] Stub contractor passes verification → sees type selection (not menu)
- [x] After data entry → stub deleted from stub sheet, full contractor created in typed sheet
- [x] Contractor id and secret_code preserved from stub
- [x] Non-stub contractors still bind normally and see menu

---

## Phase 3 — Contractor Type Change

### 3.1 Add `change_contractor_type` to contractor_repo

**File:** `src/backend/infrastructure/repositories/sheets/contractor_repo.py`

```python
def change_contractor_type(
    old_contractor: Contractor, new_type: ContractorType, new_data: dict[str, str],
) -> Contractor:
    """Delete old contractor, create new one with new type.

    Preserves: id, aliases, role_code, is_photographer, telegram, secret_code, mags.
    Resets: invoice_number to 0.
    Takes from new_data: all type-specific fields + email, bank fields.
    """
    delete_contractor_from_sheet(old_contractor.id)
    cls = CONTRACTOR_CLASS_BY_TYPE[new_type]
    kwargs = {
        "id": old_contractor.id,
        "aliases": old_contractor.aliases,
        "role_code": old_contractor.role_code,
        "is_photographer": old_contractor.is_photographer,
        "telegram": old_contractor.telegram,
        "secret_code": old_contractor.secret_code,
        "email": new_data.get("email", old_contractor.email),
        "bank_name": new_data.get("bank_name", ""),
        "bank_account": new_data.get("bank_account", ""),
        "mags": old_contractor.mags,
        "invoice_number": 0,
    }
    for field in cls.FIELD_META:
        if field not in kwargs:
            kwargs[field] = new_data.get(field, "")
    contractor = cls(**kwargs)
    save_contractor(contractor)
    logger.info("Changed %s type to %s", old_contractor.id, new_type.value)
    return contractor
```

**Done when:**
- [x] Deletes from old sheet, creates in new sheet
- [x] id, aliases, role_code, telegram, secret_code preserved
- [x] invoice_number reset to 0
- [x] Type-specific fields populated from new_data

---

### 3.2 Add type change interact flow

**File:** `src/backend/interact/__init__.py`

Add to `_HANDLERS`:
```python
"change_type": _contractor.change_type,
```

**File:** `src/backend/interact/contractor.py`

Add handler:
```python
def change_type(self, _payload: Payload, ctx: InteractContext) -> dict:
    """Start type change flow."""
    contractor_id = ctx.get("fsm_data", {}).get("target_contractor_id")
    if contractor_id:
        contractor = find_contractor_by_id(contractor_id, load_all_contractors())
    else:
        contractor, _ = self._get_contractor(ctx["user_id"])
    if not contractor:
        return respond([msg("Контрагент не найден.")], fsm_state=None)
    if contractor.is_stub:
        return respond([msg("Заглушка не имеет типа.")], fsm_state=None)
    return respond(
        [msg(f"Текущий тип: {contractor.type.value}. Выберите новый тип:"),
         self._type_selection_prompt()],
        fsm_state="waiting_type",
        fsm_data={"alias": contractor.display_name,
                  "changing_type_id": contractor.id},
    )
```

In `_complete_registration`, handle `changing_type_id`:
```python
changing_type_id = fsm_data.get("changing_type_id")
if changing_type_id:
    contractor = self._execute_type_change(changing_type_id, collected, ctype, contractors)
    secret_code = contractor.secret_code
```

Full updated `_complete_registration`:
```python
def _complete_registration(self, collected, ctype, cls, raw_text, ctx):
    self._maybe_add_russian_alias(collected, ctype)
    telegram_id = str(ctx["user_id"])
    contractors = load_all_contractors()
    fsm_data = ctx.get("fsm_data", {})
    claiming_stub_id = fsm_data.get("claiming_stub_id")
    changing_type_id = fsm_data.get("changing_type_id")
    if claiming_stub_id:
        contractor, secret_code = self._upgrade_stub(
            claiming_stub_id, collected, ctype, telegram_id, contractors)
    elif changing_type_id:
        contractor = self._execute_type_change(changing_type_id, collected, ctype, contractors)
        secret_code = contractor.secret_code
    else:
        contractor, secret_code = ContractorFactory().create(
            collected, ctype, telegram_id, contractors)
    sides = self._admin_registration_notify(collected, ctype, raw_text, ctx.get("admin_ids", []))
    messages = [self._registration_complete_msg(cls, collected, secret_code)]
    return self._try_invoice_after_registration(contractor, messages, sides)
```

Add `_execute_type_change`:
```python
def _execute_type_change(self, contractor_id, collected, new_type, contractors):
    from backend.infrastructure.repositories.sheets.contractor_repo import change_contractor_type
    old = find_contractor_by_id(contractor_id, contractors)
    return change_contractor_type(old, new_type, collected)
```

Add menu button. In `_menu_keyboard`:
```python
rows.append([{"text": "Сменить тип контрагента", "data": "menu:change_type"}])
```

In `menu_callback`, add case:
```python
if action == "change_type":
    return self.change_type(payload, ctx)
```

**Done when:**
- [x] Contractor can change type from menu button
- [x] Admin can initiate type change via `target_contractor_id` in fsm_data
- [x] After type change, data entry flow lets contractor fill new type-specific fields
- [x] Old sheet row deleted, new sheet row created

---

## Phase 4 — Contractor Lookup in Redirect Flow

### 4.1 Modify redirect source flow to search before creating

**File:** `src/backend/interact/contractor.py`

Replace `_add_editor_source`:
```python
def _add_editor_source(self, source_name, contractor):
    """Search for existing contractor before creating redirect rule."""
    contractors = load_all_contractors()
    matches = fuzzy_find(source_name, contractors, threshold=0.6)
    if matches:
        return self._suggest_source_contractors(matches, source_name, contractor)
    return self._offer_stub_or_raw(source_name, contractor)

def _suggest_source_contractors(self, matches, source_name, editor):
    """Show matching contractors with buttons."""
    buttons = []
    for c, _ in matches[:5]:
        label = f"{c.display_name} (заглушка)" if c.is_stub else c.display_name
        buttons.append([{"text": label, "data": f"esrc:link:{c.id}"}])
    buttons.append([{"text": "Создать заглушку", "data": "esrc:stub"}])
    buttons.append([{"text": "Добавить как есть", "data": "esrc:raw"}])
    return respond(
        [msg(f"Найдены похожие контрагенты для «{source_name}»:", keyboard=buttons)],
        fsm_data={"editor_id": editor.id, "pending_source_name": source_name},
    )

def _offer_stub_or_raw(self, source_name, editor):
    """No matches — offer stub creation or raw add."""
    buttons = [
        [{"text": "Создать заглушку", "data": "esrc:stub"}],
        [{"text": "Добавить как есть", "data": "esrc:raw"}],
    ]
    return respond(
        [msg(f"Контрагент «{source_name}» не найден.", keyboard=buttons)],
        fsm_data={"editor_id": editor.id, "pending_source_name": source_name},
    )
```

---

### 4.2 Extend `esrc_callback` for new actions

**File:** `src/backend/interact/contractor.py`

Extend `esrc_callback`:
```python
def esrc_callback(self, payload: Payload, ctx: InteractContext) -> dict:
    data = payload.get("callback_data", "").removeprefix("esrc:")
    contractor, _ = self._get_contractor(ctx["user_id"])
    if not contractor:
        return respond([msg("Контрагент не найден.")])

    if data.startswith("rm:"):
        return self._remove_editor_source(data.removeprefix("rm:"), contractor)
    if data == "add":
        return respond([msg("Введите имя автора.\nОтправьте «отмена» для отмены.")],
                      fsm_state="waiting_editor_source_name")
    if data == "back":
        return respond([msg("Что хотите сделать?", keyboard=self._menu_keyboard(contractor))])

    # New: source linking with suggestions
    fsm_data = ctx.get("fsm_data", {})
    source_name = fsm_data.get("pending_source_name", "")
    editor_id = fsm_data.get("editor_id", contractor.id)
    editor = find_contractor_by_id(editor_id, load_all_contractors()) or contractor

    if data.startswith("link:"):
        return self._finalize_editor_source(source_name, editor)
    if data == "stub":
        return self._create_stub_and_link(source_name, editor)
    if data == "raw":
        return self._finalize_editor_source(source_name, editor)

    return respond([msg("Неизвестное действие.")])
```

Add helpers:
```python
def _create_stub_and_link(self, source_name, editor):
    """Create a stub contractor, then add redirect rule."""
    contractors = load_all_contractors()
    ContractorFactory().create_stub(source_name, contractors)
    return self._finalize_editor_source(source_name, editor)

def _finalize_editor_source(self, source_name, editor):
    """Add redirect rule and update budget."""
    month = prev_month()
    add_redirect_rule(source_name, editor.id)
    delete_invoice(editor.id, month)
    redirect_in_budget(source_name, editor, month)
    rules = find_redirect_rules_by_target(editor.id)
    text, keyboard = self._editor_keyboard(rules)
    return respond([msg(f"Автор «{source_name}» добавлен."),
                    msg(text, keyboard=keyboard)], fsm_state=None)
```

**Done when:**
- [x] Editor enters source name → fuzzy search runs, suggestions shown with buttons
- [x] "Создать заглушку" creates stub + adds redirect rule
- [x] "Добавить как есть" adds redirect rule with raw name
- [x] Clicking an existing contractor link adds redirect rule with source_name

---

## Phase 5 — Natural Language Contractor Operations

### 5.1 Create migration for `editor_dm` environment

**File:** `src/backend/infrastructure/repositories/postgres/migrations/008_editor_dm_environment.sql`

```sql
-- 008: editor_dm environment and contractors tool permissions.

INSERT INTO environments (name, description, system_context) VALUES
  ('editor_dm', 'Личный чат с редактором/администратором Republic',
   'Это личный чат с редактором или администратором. Помогай с управлением контрагентами, редиректами, ставками. Отвечай по-русски, кратко.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO tool_permissions (tool_name, environment, allowed_roles) VALUES
    ('contractors', 'editor_dm',  ARRAY['admin', 'editor']),
    ('contractors', 'admin_dm',   ARRAY['admin', 'editor']),
    ('contractors', '*',          ARRAY['admin'])
ON CONFLICT DO NOTHING;
```

**Done when:** `editor_dm` environment created; `contractors` tool granted for admin+editor in `editor_dm` and `admin_dm`.

---

### 5.2 Add CRUD for `ArticleRateRule`

**File:** `src/backend/infrastructure/repositories/sheets/rules_repo.py`

Add constant:
```python
_ARTICLE_RATE_RANGE = "'per_article_rate_rules'!A:Z"
```

Add functions:
```python
def upsert_article_rate_rule(contractor_id: str, eur: int = 0, rub: int = 0) -> None:
    """Set or update per-article rate for a contractor."""
    raw_rows = _sheets.read(SPECIAL_RULES_SHEET_ID, _ARTICLE_RATE_RANGE)
    if len(raw_rows) < 2:
        _sheets.append(SPECIAL_RULES_SHEET_ID, _ARTICLE_RATE_RANGE,
                       [[contractor_id, str(eur), str(rub)]])
        return
    for i, row in enumerate(raw_rows[1:], start=2):
        cid = (row[0] if len(row) > 0 else "").strip()
        if cid == contractor_id:
            _sheets.write(SPECIAL_RULES_SHEET_ID,
                          f"'per_article_rate_rules'!A{i}:C{i}",
                          [[contractor_id, str(eur), str(rub)]])
            return
    _sheets.append(SPECIAL_RULES_SHEET_ID, _ARTICLE_RATE_RANGE,
                   [[contractor_id, str(eur), str(rub)]])


def get_article_rate_rule(contractor_id: str) -> ArticleRateRule | None:
    """Get per-article rate for a specific contractor."""
    for rule in load_article_rate_rules():
        if rule.contractor_id == contractor_id:
            return rule
    return None
```

**Done when:**
- [x] `upsert_article_rate_rule("c001", eur=150)` creates or updates the row
- [x] `get_article_rate_rule("c001")` returns the rule

---

### 5.3 Create `contractors` tool

**File:** `src/backend/brain/tools/contractors.py`

```python
"""Contractors tool — NL contractor operations for editors/admins."""

from __future__ import annotations

import logging

from backend.brain.tool import Tool, ToolContext
from backend.commands.contractor.create import ContractorFactory
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.repositories.sheets.contractor_repo import (
    find_contractor,
    fuzzy_find,
    load_all_contractors,
)
from backend.infrastructure.repositories.sheets.rules_repo import (
    add_redirect_rule,
    get_article_rate_rule,
    upsert_article_rate_rule,
)

logger = logging.getLogger(__name__)


def _lookup(args: dict) -> dict:
    query = args.get("name", "")
    if not query:
        return {"error": "Нужно указать name"}
    contractors = load_all_contractors()
    matches = fuzzy_find(query, contractors, threshold=0.5)
    if not matches:
        return {"result": "Контрагент не найден", "suggestions": []}
    return {"contractors": [
        {"id": c.id, "name": c.display_name,
         "type": "stub" if c.is_stub else c.type.value,
         "score": round(score, 2)}
        for c, score in matches[:5]
    ]}


def _create_stub(args: dict) -> dict:
    name = args.get("name", "")
    if not name:
        return {"error": "Нужно указать name"}
    contractors = load_all_contractors()
    existing = fuzzy_find(name, contractors, threshold=0.9)
    if existing:
        return {"error": f"«{existing[0][0].display_name}» уже существует"}
    stub, code = ContractorFactory().create_stub(name, contractors)
    return {"created": {"id": stub.id, "name": stub.display_name, "secret_code": code},
            "confirmation": f"Заглушка создана: {stub.display_name} ({stub.id})"}


def _add_redirect(args: dict) -> dict:
    source_name = args.get("source_name", "")
    target_name = args.get("target_name", "")
    if not source_name or not target_name:
        return {"error": "Нужны source_name и target_name"}
    contractors = load_all_contractors()
    target = find_contractor(target_name, contractors)
    if not target:
        return {"error": f"Контрагент «{target_name}» не найден"}
    add_redirect_rule(source_name, target.id)
    return {"confirmation": f"Редирект: {source_name} → {target.display_name} ({target.id})"}


def _set_rate(args: dict) -> dict:
    name = args.get("name", "")
    eur = args.get("eur", 0)
    rub = args.get("rub", 0)
    if not name:
        return {"error": "Нужно указать name"}
    if not eur and not rub:
        return {"error": "Нужно указать eur или rub"}
    contractors = load_all_contractors()
    contractor = find_contractor(name, contractors)
    if not contractor:
        return {"error": f"Контрагент «{name}» не найден"}
    upsert_article_rate_rule(contractor.id, eur=int(eur), rub=int(rub))
    return {"confirmation": f"Ставка для {contractor.display_name}: EUR {eur}, RUB {rub}"}


def _get_rate(args: dict) -> dict:
    name = args.get("name", "")
    if not name:
        return {"error": "Нужно указать name"}
    contractors = load_all_contractors()
    contractor = find_contractor(name, contractors)
    if not contractor:
        return {"error": f"Контрагент «{name}» не найден"}
    rule = get_article_rate_rule(contractor.id)
    if not rule:
        return {"result": f"Для {contractor.display_name} не задана поартикульная ставка"}
    return {"contractor": contractor.display_name, "eur": rule.eur, "rub": rule.rub}


_ACTIONS = {
    "lookup": _lookup,
    "create_stub": _create_stub,
    "add_redirect": _add_redirect,
    "set_rate": _set_rate,
    "get_rate": _get_rate,
}


def make_contractors_tool(gemini: GeminiGateway) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        action = args.get("action", "lookup")
        handler = _ACTIONS.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return handler(args)

    return Tool(
        name="contractors",
        description="Управление контрагентами: поиск, создание заглушки, редиректы оплаты, ставки за статью",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["lookup", "create_stub", "add_redirect", "set_rate", "get_rate"],
                    "description": "lookup=найти, create_stub=заглушка, add_redirect=редирект, set_rate=задать ставку, get_rate=узнать ставку",
                },
                "name": {"type": "string", "description": "Имя контрагента"},
                "source_name": {"type": "string", "description": "Имя-источник для редиректа"},
                "target_name": {"type": "string", "description": "Имя получателя редиректа"},
                "eur": {"type": "integer", "description": "Ставка EUR за статью"},
                "rub": {"type": "integer", "description": "Ставка RUB за статью"},
            },
            "required": ["action"],
        },
        fn=fn,
        permissions={},
        slash_command=None,
        examples=[
            "найди контрагента Иванов",
            "создай заглушку для нового автора",
            "я получаю ещё за Петрова",
            "автор X получает 150 евро за статью",
            "какая ставка у Иванова",
        ],
        nl_routable=True,
        conversational=True,
    )
```

**Done when:**
- [x] All 5 actions work correctly
- [x] Tool is conversational and nl_routable

---

### 5.4 Register `contractors` tool

**File 1:** `src/backend/brain/tools/__init__.py`

Add import: `from backend.brain.tools.contractors import make_contractors_tool`

Add to `__all__`: `"make_contractors_tool",`

**File 2:** `src/backend/wiring.py`

Add `make_contractors_tool` to the import from `backend.brain.tools`.

In `_register_core_tools`, add:
```python
register_tool(make_contractors_tool(gemini))
```

**Done when:**
- [x] `contractors` appears in `TOOLS` dict at startup
- [x] Authorized for admin+editor in editor_dm and admin_dm via tool_permissions

---

### 5.5 Bot routing: admin DM free text → Brain NL

**File:** `src/client/telegram_bot/router.py`

Current catch-all in `_route_text` (line ~392-393):
```python
await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
await handle_contractor_text(message, state)
```

Change to route admin free text through Brain NL:
```python
    # Admin/editor DMs: route through Brain NL (contractors tool available)
    if is_admin(message.from_user.id):
        await _route_admin_dm_nl(message, state, text)
        return
    # Contractors: existing flow
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await handle_contractor_text(message, state)
```

Add helper function:
```python
async def _route_admin_dm_nl(message: types.Message, state: FSMContext, text: str) -> None:
    """Route admin DM free text through Brain NL."""
    from telegram_bot.handlers.conversation_handlers import (
        _dispatch_nl_result,
        _stream_with_thinking,
    )
    thinking = None
    try:
        thinking, result = await _stream_with_thinking(
            message, thinking, input=text)
        await _dispatch_nl_result(message, text, result, thinking)
    except Exception:
        if thinking:
            await thinking.__aexit__(None, None, None)
        logger.exception("Admin DM NL failed")
        await message.answer("Не удалось обработать.")
```

**Important:** The `environment_id` used by Brain is derived from `chat_id`. Admin DM chats should be bound to `admin_dm` (existing) or `editor_dm` (new). The `Authorizer` resolves environment from chat binding and filters tools by role.

**Done when:**
- [ ] Admin sends free text in DM → goes through Brain NL (contractors tool available)
- [ ] Admin sends `/generate Test` → still goes through slash command (line 382-383)
- [ ] Contractor sends free text → still goes through contractor flow
- [ ] Admin reply-to still works (line 385-387)
- [ ] FSM states still work for admins (line 388-391)

---

## Phase 6 — Tests

### 6.1 Test improved fuzzy matching

**File:** `tests/test_fuzzy_matching.py`

Create test file with a mock contractor helper:

```python
from unittest.mock import MagicMock

from backend.infrastructure.repositories.sheets.contractor_repo import (
    fuzzy_find,
    _word_independent_score,
)


def _make_contractor(name):
    c = MagicMock()
    c.all_names = [name]
    return c
```

- [x] `test_word_order_ru` — `fuzzy_find("Иванов Петр", [_make_contractor("Петр Иванов")])` returns match >= 0.8
- [x] `test_word_order_en` — `fuzzy_find("Smith John", [_make_contractor("John Smith")])` returns match >= 0.8
- [x] `test_substring_still_works` — `fuzzy_find("Иван", [_make_contractor("Иванов")])` returns match 0.95
- [x] `test_threshold_respected` — `fuzzy_find("xyz", [_make_contractor("Петр Иванов")], threshold=0.9)` returns empty
- [x] `test_low_threshold_catches_loose` — `fuzzy_find("Иван", [_make_contractor("Иванов Петр Сергеевич")], threshold=0.6)` returns match
- [x] `test_word_independent_score_basic` — `_word_independent_score("Петр Иванов", "Иванов Петр")` returns 1.0

---

### 6.2 Test stub contractor flow

**File:** `tests/test_interact.py` (append)

- [ ] `test_stub_verification_starts_type_selection` — mock stub contractor with `is_stub=True`, verify after correct code: `fsm_state="waiting_type"` and `claiming_stub_id` in fsm_data
- [ ] `test_non_stub_verification_goes_to_menu` — mock normal contractor, verify `fsm_state=None` and keyboard present (already covered by `test_verification_correct_code_binds`, but add `is_stub=False` explicitly)

---

### 6.3 Test type change

**File:** `tests/test_interact.py` (append)

- [ ] `test_change_type_from_menu` — mock contractor, call `menu_callback` with `"menu:change_type"`, verify `fsm_state="waiting_type"` and `changing_type_id` in fsm_data
- [ ] `test_change_type_stub_rejected` — mock stub contractor, call `change_type`, verify error message

---

### 6.4 Test redirect source lookup

**File:** `tests/test_interact.py` (append)

- [ ] `test_editor_source_name_shows_suggestions` — mock `fuzzy_find` to return matches, verify keyboard with `esrc:link:` buttons and `esrc:stub` button
- [ ] `test_editor_source_name_no_match_offers_stub` — mock `fuzzy_find` returning empty, verify keyboard with `esrc:stub` and `esrc:raw` buttons
- [ ] `test_esrc_callback_raw_adds_rule` — mock `add_redirect_rule`, callback `esrc:raw` with `pending_source_name` in fsm_data, verify redirect added
- [ ] `test_esrc_callback_stub_creates_and_links` — mock `ContractorFactory.create_stub` + `add_redirect_rule`, callback `esrc:stub`, verify both called

---

### 6.5 Test contractors tool

**File:** `tests/test_contractors_tool.py`

- [ ] `test_lookup_found` — mock `fuzzy_find` returning matches, verify `{"contractors": [...]}`
- [ ] `test_lookup_not_found` — mock `fuzzy_find` returning empty, verify `{"suggestions": []}`
- [ ] `test_create_stub_success` — mock `ContractorFactory.create_stub`, verify `{"created": {...}}`
- [ ] `test_create_stub_duplicate` — mock `fuzzy_find` returning high match, verify `{"error": ...}`
- [ ] `test_add_redirect` — mock `find_contractor` + `add_redirect_rule`, verify confirmation
- [ ] `test_set_rate` — mock `find_contractor` + `upsert_article_rate_rule`, verify confirmation
- [ ] `test_get_rate_exists` — mock `get_article_rate_rule` returning rule, verify eur/rub
- [ ] `test_get_rate_missing` — mock returning None, verify message

---

## Phase 7 — Documentation & External TODOs

### 7.1 Update `docs/diagrams/brain-flows.md`

Add `contractors` to the Tools list in "Component Wiring" section:
```
│  ├── contractors   (conv, routable) │
```

Add to "Conversational Tools" list:
```
- `contractors` — contractor lookup, stub creation, redirects, article rates
```

---

### 7.2 Update `autonomous/dev/external-todo.md`

```markdown
## Contractor Operations Overhaul (Plan 13)

- [ ] Create "stub" tab in the contractors Google Sheet with header: `id | name | aliases | role_code | telegram | secret_code`
- [ ] Deploy migration 008 (editor_dm environment + contractors tool permissions)
- [ ] Bind editor DM chats to `editor_dm` environment via API
- [ ] Create editor users with role `editor` so Authorizer grants correct tools
- [ ] Test self-registration with improved matching threshold (0.6)
- [ ] Test type change flow end-to-end: samozanyaty → global
- [ ] Test stub claim flow: admin creates stub → author starts bot → matches → verifies → fills data
- [ ] Test NL contractor operations in admin DM
```

---

## Implementation Order

```
Phase 1 (1.1 → 1.2) — Fuzzy matching improvements (foundation)
  ↓
Phase 2 (2.1 → 2.2 → 2.3 → 2.4) — Stub contractors
  ↓
Phase 3 (3.1 → 3.2) — Type change
  ↓
Phase 4 (4.1 → 4.2) — Redirect source lookup (depends on stubs + matching)
  ↓
Phase 5 (5.1 → 5.2 → 5.3 → 5.4 → 5.5) — NL tool + editor_dm
  ↓
Phase 6 (6.1 → 6.2 → 6.3 → 6.4 → 6.5) — Tests
  ↓
Phase 7 (7.1 → 7.2) — Docs & external TODOs
```

## Files Created (new)
- `src/backend/infrastructure/repositories/postgres/migrations/008_editor_dm_environment.sql`
- `src/backend/brain/tools/contractors.py`
- `tests/test_fuzzy_matching.py`
- `tests/test_contractors_tool.py`

## Files Modified
- `src/backend/models.py` — `StubContractor`, `ContractorType.STUB`, `is_stub` property
- `src/backend/infrastructure/repositories/sheets/contractor_repo.py` — `_word_independent_score`, `_normalize_words`, `_parse_stub`, `load_all_contractors` (stubs), `save_stub`, `delete_contractor_from_sheet`, `change_contractor_type`
- `src/backend/infrastructure/repositories/sheets/rules_repo.py` — `upsert_article_rate_rule`, `get_article_rate_rule`
- `src/backend/commands/contractor/create.py` — `create_stub` method
- `src/backend/interact/contractor.py` — threshold 0.6, `_bind_contractor` stub flow, `_upgrade_stub`, `change_type` handler, `_execute_type_change`, `_add_editor_source` with lookup, `_suggest_source_contractors`, `_offer_stub_or_raw`, `_create_stub_and_link`, `_finalize_editor_source`, `esrc_callback` extensions, `menu_callback` change_type case, `_menu_keyboard` button
- `src/backend/interact/__init__.py` — `change_type` action in `_HANDLERS`
- `src/backend/brain/tools/__init__.py` — export `make_contractors_tool`
- `src/backend/wiring.py` — register `contractors` tool
- `src/client/telegram_bot/router.py` — admin DM NL routing in `_route_text`
- `tests/test_interact.py` — stub, type change, redirect lookup tests
- `docs/diagrams/brain-flows.md` — contractors tool in diagram
- `autonomous/dev/external-todo.md` — manual steps
