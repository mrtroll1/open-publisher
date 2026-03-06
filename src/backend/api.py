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
_classify_teaching = _components.classify_teaching


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Request / Response models ---

class ProcessRequest(BaseModel):
    input: str
    environment_id: str = "default"
    user_id: str = ""
    chat_id: int | None = None
    reply_to_message_id: int | None = None
    reply_to_text: str = ""

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

class ClassifyRequest(BaseModel):
    text: str

class UserNoteRequest(BaseModel):
    text: str
    domain: str = "general"

class EntryUpdateRequest(BaseModel):
    content: str

class UidRequest(BaseModel):
    uid: str

class UidTextRequest(BaseModel):
    uid: str
    text: str

class MessageSaveRequest(BaseModel):
    text: str
    environment: str | None = None
    chat_id: int | None = None
    type: str = "user"
    user_id: str | None = None
    parent_id: str | None = None
    metadata: dict | None = None

class EnvironmentCreateRequest(BaseModel):
    name: str
    description: str
    system_context: str = ""

class EnvironmentUpdateRequest(BaseModel):
    name: str
    description: str | None = None
    system_context: str | None = None
    allowed_domains: list[str] | None = None

class EnvironmentBindRequest(BaseModel):
    chat_id: int
    name: str

class MessageUpdateMetadataRequest(BaseModel):
    updates: dict

class StoreFeedbackRequest(BaseModel):
    text: str
    domain: str


# --- Brain endpoints ---

@app.post("/brain/process")
def process(req: ProcessRequest) -> BrainResponse:
    try:
        kwargs = {}
        if req.chat_id is not None:
            kwargs["chat_id"] = req.chat_id
        if req.reply_to_message_id is not None:
            kwargs["reply_to_message_id"] = req.reply_to_message_id
            kwargs["reply_to_text"] = req.reply_to_text
        result = brain.process(req.input, req.environment_id, req.user_id, **kwargs)
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
    """Fetch unread emails, classify each, return processed items with drafts."""
    try:
        emails = inbox.fetch_unread()
        results = []
        for em in emails:
            item = inbox.process(em)
            if not item:
                continue
            entry = {"category": item.category, "uid": item.uid}
            if item.category == "tech_support" and item.draft:
                d = item.draft
                entry["draft"] = {
                    "uid": d.email.uid,
                    "from_addr": d.email.from_addr,
                    "reply_to": d.email.reply_to,
                    "subject": d.email.subject,
                    "body": d.email.body[:500],
                    "draft_reply": d.draft_reply,
                    "can_answer": d.can_answer,
                }
            elif item.category == "editorial" and item.editorial:
                e = item.editorial
                entry["editorial"] = {
                    "uid": e.email.uid,
                    "from_addr": e.email.from_addr,
                    "subject": e.email.subject,
                    "body": e.email.body[:500],
                    "reply_to_sender": e.reply_to_sender,
                }
            results.append(entry)
        return BrainResponse(result=results)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/inbox/update-and-approve-support")
def update_and_approve_support(req: UidTextRequest) -> BrainResponse:
    try:
        inbox.update_and_approve_support(req.uid, req.text)
        return BrainResponse(result="ok")
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/inbox/pending-support/{uid}")
def get_pending_support(uid: str) -> BrainResponse:
    try:
        draft = inbox.get_pending_support(uid)
        if not draft:
            return BrainResponse(result=None)
        return BrainResponse(result={
            "uid": draft.email.uid,
            "from_addr": draft.email.from_addr,
            "reply_to": draft.email.reply_to,
            "subject": draft.email.subject,
            "body": draft.email.body[:500],
            "draft_reply": draft.draft_reply,
            "can_answer": draft.can_answer,
        })
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/inbox/pending-editorial/{uid}")
def get_pending_editorial(uid: str) -> BrainResponse:
    try:
        item = inbox.get_pending_editorial(uid)
        if not item:
            return BrainResponse(result=None)
        return BrainResponse(result={
            "uid": item.email.uid,
            "from_addr": item.email.from_addr,
            "subject": item.email.subject,
            "body": item.email.body[:500],
            "reply_to_sender": item.reply_to_sender,
        })
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

@app.post("/memory/classify-teaching")
def classify_teaching(req: ClassifyRequest) -> BrainResponse:
    try:
        result = _classify_teaching.run(req.text, {})
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/memory/search")
def memory_search(query: str, domain: str | None = None) -> BrainResponse:
    try:
        results = memory.recall(query, domain=domain)
        return BrainResponse(result=results)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/memory/list")
def memory_list(domain: str | None = None, tier: str | None = None) -> BrainResponse:
    try:
        results = memory.list_knowledge(domain=domain, tier=tier)
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

@app.get("/memory/environment")
def get_environment(chat_id: int = 0, name: str = "") -> BrainResponse:
    try:
        result = memory.get_environment(name=name, chat_id=chat_id)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/memory/environment/create")
def create_environment(req: EnvironmentCreateRequest) -> BrainResponse:
    try:
        db.save_environment(req.name, req.description, req.system_context)
        return BrainResponse(result="ok")
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.put("/memory/environment/update")
def update_environment(req: EnvironmentUpdateRequest) -> BrainResponse:
    try:
        kwargs = {}
        if req.description is not None:
            kwargs["description"] = req.description
        if req.system_context is not None:
            kwargs["system_context"] = req.system_context
        if req.allowed_domains is not None:
            kwargs["allowed_domains"] = req.allowed_domains
        ok = memory.update_environment(req.name, **kwargs)
        return BrainResponse(result=ok)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/memory/environment/bind")
def bind_environment(req: EnvironmentBindRequest) -> BrainResponse:
    try:
        db.bind_chat(req.chat_id, req.name)
        return BrainResponse(result="ok")
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/memory/environment/unbind")
def unbind_environment(chat_id: int) -> BrainResponse:
    try:
        db.unbind_chat(chat_id)
        return BrainResponse(result="ok")
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/memory/environment/bindings")
def get_bindings(name: str) -> BrainResponse:
    try:
        return BrainResponse(result=db.get_bindings_for_environment(name))
    except Exception as e:
        return BrainResponse(result=None, error=str(e))


# --- User endpoints ---

@app.get("/user/admin_telegram_ids")
def get_admin_telegram_ids() -> BrainResponse:
    try:
        return BrainResponse(result=db.get_admin_telegram_ids())
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/user/is_admin")
def is_admin_check(telegram_id: int) -> BrainResponse:
    try:
        user = db.get_user_by_telegram_id(telegram_id)
        return BrainResponse(result=bool(user and user["role"] == "admin"))
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/user/context")
def get_user_context(telegram_id: int) -> BrainResponse:
    try:
        user = db.get_user_by_telegram_id(telegram_id)
        if not user:
            return BrainResponse(result="")
        context = retriever.get_user_context(user["id"])
        return BrainResponse(result=context)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/user/{user_id}/note")
def add_user_note(user_id: str, req: UserNoteRequest) -> BrainResponse:
    try:
        entry_id = memory.remember(req.text, domain=req.domain,
                                   source="api", user_id=user_id)
        return BrainResponse(result={"id": entry_id})
    except Exception as e:
        return BrainResponse(result=None, error=str(e))


# --- Message endpoints ---

@app.post("/message/save")
def save_message(req: MessageSaveRequest) -> BrainResponse:
    try:
        msg_id = db.save_message(
            text=req.text, environment=req.environment,
            chat_id=req.chat_id, type=req.type,
            user_id=req.user_id, parent_id=req.parent_id,
            metadata=req.metadata,
        )
        return BrainResponse(result={"id": msg_id})
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.get("/message/by-telegram-id")
def get_by_telegram_message_id(chat_id: int, telegram_message_id: int) -> BrainResponse:
    try:
        return BrainResponse(result=db.get_by_telegram_message_id(chat_id, telegram_message_id))
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.put("/message/{message_id}/metadata")
def update_message_metadata(message_id: str, req: MessageUpdateMetadataRequest) -> BrainResponse:
    try:
        db.update_metadata(message_id, req.updates)
        return BrainResponse(result="ok")
    except Exception as e:
        return BrainResponse(result=None, error=str(e))


class InteractRequest(BaseModel):
    action: str
    payload: dict = {}
    context: dict = {}

@app.post("/interact")
def interact(req: InteractRequest) -> BrainResponse:
    from backend.interact import handle
    try:
        result = handle(req.action, req.payload, req.context)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))


@app.post("/admin/store-feedback")
def store_feedback(req: StoreFeedbackRequest) -> BrainResponse:
    try:
        memory.remember(req.text, domain=req.domain, source="admin_feedback")
        return BrainResponse(result="ok")
    except Exception as e:
        return BrainResponse(result=None, error=str(e))
