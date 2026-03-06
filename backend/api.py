from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

from backend.wiring import create_brain

app = FastAPI(title="Republic Agent Backend")
_components = create_brain()
brain = _components.brain
memory = _components.memory
inbox = _components.inbox
db = _components.db
retriever = _components.retriever


# --- Request / Response models ---

class ProcessRequest(BaseModel):
    input: str
    environment_id: str = "default"
    user_id: str = ""

class CommandRequest(BaseModel):
    command: str
    args: str = ""
    environment_id: str = "default"
    user_id: str = ""

class BrainResponse(BaseModel):
    result: Any
    error: str = ""

class TeachRequest(BaseModel):
    text: str
    domain: str
    tier: str = "specific"

class EntityAddRequest(BaseModel):
    kind: str
    name: str
    external_ids: dict | None = None
    summary: str = ""

class EntityNoteRequest(BaseModel):
    text: str
    domain: str = "entity_notes"

class EntryUpdateRequest(BaseModel):
    content: str

class UidRequest(BaseModel):
    uid: str

class ConversationSaveRequest(BaseModel):
    chat_id: int
    user_id: int
    role: str
    content: str
    reply_to_id: str | None = None
    message_id: int | None = None
    metadata: dict | None = None


# --- Brain endpoints ---

@app.post("/brain/process")
def process(req: ProcessRequest) -> BrainResponse:
    try:
        result = brain.process(req.input, req.environment_id, req.user_id)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/brain/command")
def command(req: CommandRequest) -> BrainResponse:
    try:
        result = brain.process_command(req.command, req.args, req.environment_id, req.user_id)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))


# --- Inbox endpoints ---

@app.post("/inbox/approve-support")
def approve_support(req: UidRequest) -> BrainResponse:
    try:
        result = inbox.approve_support(req.uid)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/inbox/skip-support")
def skip_support(req: UidRequest) -> BrainResponse:
    try:
        inbox.skip_support(req.uid)
        return BrainResponse(result="ok")
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/inbox/approve-editorial")
def approve_editorial(req: UidRequest) -> BrainResponse:
    try:
        result = inbox.approve_editorial(req.uid)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/inbox/skip-editorial")
def skip_editorial(req: UidRequest) -> BrainResponse:
    try:
        inbox.skip_editorial(req.uid)
        return BrainResponse(result="ok")
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/inbox/fetch-unread")
def fetch_unread() -> BrainResponse:
    try:
        result = inbox.fetch_unread()
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))


# --- Memory endpoints ---

@app.post("/memory/teach")
def teach(req: TeachRequest) -> BrainResponse:
    try:
        entry_id = memory.teach(req.text, req.domain, req.tier)
        return BrainResponse(result={"id": entry_id})
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/memory/search")
def memory_search(query: str, domain: str | None = None) -> BrainResponse:
    try:
        results = memory.recall(query, domain=domain)
        return BrainResponse(result=results)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/memory/entry/{entry_id}")
def get_entry(entry_id: str) -> BrainResponse:
    try:
        entry = memory.get_entry(entry_id)
        return BrainResponse(result=entry)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.put("/memory/entry/{entry_id}")
def update_entry(entry_id: str, req: EntryUpdateRequest) -> BrainResponse:
    try:
        ok = memory.update_entry(entry_id, req.content)
        return BrainResponse(result=ok)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.delete("/memory/entry/{entry_id}")
def delete_entry(entry_id: str) -> BrainResponse:
    try:
        ok = memory.deactivate_entry(entry_id)
        return BrainResponse(result=ok)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/memory/domains")
def list_domains() -> BrainResponse:
    try:
        return BrainResponse(result=memory.list_domains())
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/memory/environments")
def list_environments() -> BrainResponse:
    try:
        return BrainResponse(result=memory.list_environments())
    except Exception as e:
        return BrainResponse(result=None, error=str(e))


# --- Entity endpoints ---

@app.post("/entity/add")
def add_entity(req: EntityAddRequest) -> BrainResponse:
    try:
        entity_id = memory.add_entity(req.kind, req.name,
                                      external_ids=req.external_ids,
                                      summary=req.summary)
        return BrainResponse(result={"id": entity_id})
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/entity/find")
def find_entity(query: str = "", external_key: str = "",
                external_value: str = "") -> BrainResponse:
    try:
        result = memory.find_entity(query=query, external_key=external_key,
                                    external_value=external_value)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/entity/{entity_id}/note")
def add_entity_note(entity_id: str, req: EntityNoteRequest) -> BrainResponse:
    try:
        entry_id = memory.remember(req.text, domain=req.domain,
                                   source="api", entity_id=entity_id)
        return BrainResponse(result={"id": entry_id})
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/entity/context")
def get_entity_context(user_id: str) -> BrainResponse:
    """Find entity by telegram_user_id, return formatted context string."""
    try:
        entity = memory.find_entity(external_key="telegram_user_id",
                                    external_value=user_id)
        if not entity:
            return BrainResponse(result="")
        context = retriever.get_entity_context(entity["id"])
        return BrainResponse(result=context)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))


# --- Conversation endpoints ---

@app.post("/conversation/save")
def save_conversation(req: ConversationSaveRequest) -> BrainResponse:
    try:
        entry_id = db.save_conversation(
            chat_id=req.chat_id, user_id=req.user_id,
            role=req.role, content=req.content,
            reply_to_id=req.reply_to_id, message_id=req.message_id,
            metadata=req.metadata,
        )
        return BrainResponse(result={"id": entry_id})
    except Exception as e:
        return BrainResponse(result=None, error=str(e))


# --- Environment endpoint ---

@app.get("/memory/environment")
def get_environment(chat_id: int = 0, name: str = "") -> BrainResponse:
    try:
        result = memory.get_environment(name=name, chat_id=chat_id)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))
