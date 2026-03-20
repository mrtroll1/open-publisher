import json
import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from backend.brain.tool import TOOLS, ToolContext
from backend.commands.env_summarize import EnvSummarize
from backend.commands.scrape_channels import ScrapeChannels
from backend.interact import handle
from backend.models import InboxCategory, PendingItem, ProgressEmitter, ProgressEvent
from backend.wiring import create_brain

logger = logging.getLogger(__name__)

app = FastAPI(title="Republic Agent Backend")
_components = create_brain()
brain = _components.brain
memory = _components.memory
inbox = _components.inbox
db = _components.db
retriever = _components.retriever
gemini = _components.gemini


# --- SSE streaming helper ---

def _sse_stream(work_fn: Callable[[ProgressEmitter], Any]) -> StreamingResponse:
    """Run work_fn in a thread, streaming progress events via SSE."""
    event_queue: queue.Queue[ProgressEvent | None] = queue.Queue()
    emitter = ProgressEmitter(_on_event=event_queue.put)
    result_holder: list[Any] = []
    error_holder: list[str] = []

    def _run() -> None:
        try:
            result_holder.append(work_fn(emitter))
        except Exception as e:
            error_holder.append(str(e))
        finally:
            event_queue.put(None)

    thread = threading.Thread(target=_run)
    thread.start()
    return StreamingResponse(_generate(event_queue, thread, result_holder, error_holder), media_type="text/event-stream")


def _generate(event_queue, thread, result_holder, error_holder):
    while True:
        event = event_queue.get()
        if event is None:
            break
        data = json.dumps({"stage": event.stage, "detail": event.detail}, ensure_ascii=False)
        yield f"event: progress\ndata: {data}\n\n"
    thread.join()
    if error_holder:
        data = json.dumps({"result": None, "error": error_holder[0]}, ensure_ascii=False)
    else:
        data = json.dumps({"result": result_holder[0]}, ensure_ascii=False, default=str)
    yield f"event: done\ndata: {data}\n\n"


# --- Inbox helpers ---

def _email_to_entry(item: PendingItem) -> dict:
    """Convert a PendingItem to the dict format returned by fetch_unread."""
    entry = {"category": item.category, "uid": item.uid}
    if item.category == InboxCategory.TECH_SUPPORT and item.draft:
        entry["draft"] = _support_draft_dict(item.draft)
    elif item.category == InboxCategory.EDITORIAL and item.editorial:
        entry["editorial"] = _editorial_dict(item.editorial)
    return entry


def _support_draft_dict(d) -> dict:
    return {
        "uid": d.email.uid,
        "from_addr": d.email.from_addr,
        "reply_to": d.email.reply_to,
        "subject": d.email.subject,
        "body": d.email.body[:500],
        "draft_reply": d.draft_reply,
        "can_answer": d.can_answer,
    }


def _editorial_dict(e) -> dict:
    return {
        "uid": e.email.uid,
        "from_addr": e.email.from_addr,
        "subject": e.email.subject,
        "body": e.email.body[:500],
        "reply_to_sender": e.reply_to_sender,
    }


# --- Process kwargs helper ---

def _process_kwargs(req) -> dict:
    kwargs = {}
    if req.chat_id is not None:
        kwargs["chat_id"] = req.chat_id
    if req.reply_to_message_id is not None:
        kwargs["reply_to_message_id"] = req.reply_to_message_id
        kwargs["reply_to_text"] = req.reply_to_text
    return kwargs


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(content={"result": None, "error": str(exc)})


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
    result: object
    error: str = ""

class TeachRequest(BaseModel):
    text: str
    context: str = ""
    domain: str = ""
    tier: str = ""

class UserNoteRequest(BaseModel):
    text: str
    domain: str = "general"

class UserManageRequest(BaseModel):
    text: str = ""
    telegram_id: int | None = None
    name: str = ""
    role: str = "user"
    email: str | None = None

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
    telegram_handle: str | None = None

class EnvironmentUpdateRequest(BaseModel):
    name: str
    description: str | None = None
    system_context: str | None = None
    telegram_handle: str | None = None

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
    result = brain.process(req.input, req.environment_id, req.user_id, **_process_kwargs(req))
    return BrainResponse(result=result)


@app.post("/brain/process/stream")
def process_stream(req: ProcessRequest):
    """SSE endpoint: yields progress events from Brain, then the final result."""
    def work(emitter):
        kwargs = _process_kwargs(req)
        kwargs["progress"] = emitter
        return brain.process(req.input, req.environment_id, req.user_id, **kwargs)

    return _sse_stream(work)

@app.post("/brain/command")
def command(req: CommandRequest) -> BrainResponse:
    result = brain.process_command(req.command, req.args, req.environment_id, req.user_id)
    return BrainResponse(result=result)


# --- Inbox endpoints ---

@app.post("/inbox/approve-support")
def approve_support(req: UidRequest) -> BrainResponse:
    return BrainResponse(result=inbox.approve_support(req.uid))

@app.post("/inbox/skip-support")
def skip_support(req: UidRequest) -> BrainResponse:
    inbox.skip_support(req.uid)
    return BrainResponse(result="ok")

@app.post("/inbox/approve-editorial")
def approve_editorial(req: UidRequest) -> BrainResponse:
    return BrainResponse(result=inbox.approve_editorial(req.uid))

@app.post("/inbox/skip-editorial")
def skip_editorial(req: UidRequest) -> BrainResponse:
    inbox.skip_editorial(req.uid)
    return BrainResponse(result="ok")

@app.post("/inbox/fetch-unread")
def fetch_unread() -> BrainResponse:
    """Fetch unread emails, classify each, return processed items with drafts."""
    emails = inbox.fetch_unread()
    results = []
    for em in emails:
        item = inbox.process(em)
        if item:
            results.append(_email_to_entry(item))
    return BrainResponse(result=results)

@app.post("/inbox/update-and-approve-support")
def update_and_approve_support(req: UidTextRequest) -> BrainResponse:
    inbox.update_and_approve_support(req.uid, req.text)
    return BrainResponse(result="ok")

@app.get("/inbox/pending-support/{uid}")
def get_pending_support(uid: str) -> BrainResponse:
    draft = inbox.get_pending_support(uid)
    if not draft:
        return BrainResponse(result=None)
    return BrainResponse(result=_support_draft_dict(draft))

@app.get("/inbox/pending-editorial/{uid}")
def get_pending_editorial(uid: str) -> BrainResponse:
    item = inbox.get_pending_editorial(uid)
    if not item:
        return BrainResponse(result=None)
    return BrainResponse(result=_editorial_dict(item))


# --- Memory endpoints ---

@app.post("/memory/teach")
def teach(req: TeachRequest) -> BrainResponse:
    teach_tool = TOOLS["teach"]
    ctx = ToolContext(env={}, user={})
    args = {"text": req.text, "context": req.context}
    if req.domain:
        args["domain"] = req.domain
    if req.tier:
        args["tier"] = req.tier
    return BrainResponse(result=teach_tool.execute(args, ctx))

@app.get("/memory/users")
def list_users() -> BrainResponse:
    return BrainResponse(result=db.list_users())

@app.post("/memory/user")
def manage_user(req: UserManageRequest) -> BrainResponse:
    user_tool = TOOLS["user"]
    ctx = ToolContext(env={}, user={})
    args = {}
    if req.text:
        args["text"] = req.text
    if req.name:
        args["name"] = req.name
    if req.role and req.role != "user":
        args["role"] = req.role
    if req.telegram_id:
        args["telegram_id"] = req.telegram_id
    if req.email:
        args["email"] = req.email
    return BrainResponse(result=user_tool.execute(args, ctx))

@app.get("/memory/search")
def memory_search(query: str, domain: str | None = None) -> BrainResponse:
    return BrainResponse(result=memory.recall(query, domain=domain))

@app.get("/memory/list")
def memory_list(domain: str | None = None, tier: str | None = None) -> BrainResponse:
    return BrainResponse(result=memory.list_knowledge(domain=domain, tier=tier))

@app.get("/memory/entry/{entry_id}")
def get_entry(entry_id: str) -> BrainResponse:
    return BrainResponse(result=memory.get_entry(entry_id))

@app.put("/memory/entry/{entry_id}")
def update_entry(entry_id: str, req: EntryUpdateRequest) -> BrainResponse:
    return BrainResponse(result=memory.update_entry(entry_id, req.content))

@app.delete("/memory/entry/{entry_id}")
def delete_entry(entry_id: str) -> BrainResponse:
    return BrainResponse(result=memory.deactivate_entry(entry_id))

@app.get("/memory/domains")
def list_domains() -> BrainResponse:
    return BrainResponse(result=memory.list_domains())

@app.get("/memory/environments")
def list_environments() -> BrainResponse:
    return BrainResponse(result=memory.list_environments())

@app.get("/memory/environment")
def get_environment(chat_id: int = 0, name: str = "") -> BrainResponse:
    return BrainResponse(result=memory.get_environment(name=name, chat_id=chat_id))

@app.post("/memory/environment/create")
def create_environment(req: EnvironmentCreateRequest) -> BrainResponse:
    db.save_environment(req.name, req.description, req.system_context)
    if req.telegram_handle:
        db.update_environment(req.name, telegram_handle=req.telegram_handle)
    return BrainResponse(result="ok")

@app.put("/memory/environment/update")
def update_environment(req: EnvironmentUpdateRequest) -> BrainResponse:
    kwargs = {}
    if req.description is not None:
        kwargs["description"] = req.description
    if req.system_context is not None:
        kwargs["system_context"] = req.system_context
    if req.telegram_handle is not None:
        kwargs["telegram_handle"] = req.telegram_handle
    return BrainResponse(result=memory.update_environment(req.name, **kwargs))

@app.post("/memory/environment/bind")
def bind_environment(req: EnvironmentBindRequest) -> BrainResponse:
    db.bind_chat(req.chat_id, req.name)
    return BrainResponse(result="ok")

@app.post("/memory/environment/unbind")
def unbind_environment(chat_id: int) -> BrainResponse:
    db.unbind_chat(chat_id)
    return BrainResponse(result="ok")

@app.get("/memory/environment/bindings")
def get_bindings(name: str) -> BrainResponse:
    return BrainResponse(result=db.get_bindings_for_environment(name))


# --- Permissions ---

class PermGrantRequest(BaseModel):
    tool_name: str
    environment: str = "*"
    roles: list[str] = ["*"]

class PermRevokeRequest(BaseModel):
    tool_name: str
    environment: str

@app.get("/permissions")
def list_permissions() -> BrainResponse:
    return BrainResponse(result=db.list_permissions())

@app.post("/permissions/grant")
def grant_permission(req: PermGrantRequest) -> BrainResponse:
    db.grant(req.tool_name, req.environment, req.roles)
    return BrainResponse(result="ok")

@app.post("/permissions/revoke")
def revoke_permission(req: PermRevokeRequest) -> BrainResponse:
    ok = db.revoke(req.tool_name, req.environment)
    return BrainResponse(result="ok" if ok else "not_found")


# --- Notifications ---

@app.get("/notifications/pending")
def pending_notifications() -> BrainResponse:
    items = db.get_pending_notifications()
    if items:
        ids = [str(n["id"]) for n in items]
        db.mark_notifications_read(ids)
    return BrainResponse(result=items)


# --- User endpoints ---

@app.post("/user/ensure")
def ensure_user(telegram_id: int) -> BrainResponse:
    user = db.get_or_create_by_telegram_id(telegram_id)
    return BrainResponse(result=user)


@app.get("/user/admin_telegram_ids")
def get_admin_telegram_ids() -> BrainResponse:
    return BrainResponse(result=db.get_admin_telegram_ids())

@app.get("/user/is_admin")
def is_admin_check(telegram_id: int) -> BrainResponse:
    user = db.get_user_by_telegram_id(telegram_id)
    return BrainResponse(result=bool(user and user["role"] == "admin"))

@app.get("/user/context")
def get_user_context(telegram_id: int) -> BrainResponse:
    user = db.get_user_by_telegram_id(telegram_id)
    if not user:
        return BrainResponse(result="")
    return BrainResponse(result=retriever.get_user_context(user["id"]))

@app.post("/user/{user_id}/note")
def add_user_note(user_id: str, req: UserNoteRequest) -> BrainResponse:
    entry_id = memory.remember(req.text, domain=req.domain, source="api", user_id=user_id)
    return BrainResponse(result={"id": entry_id})


# --- Message endpoints ---

@app.post("/message/save")
def save_message(req: MessageSaveRequest) -> BrainResponse:
    msg_id = db.save_message(
        text=req.text, environment=req.environment,
        chat_id=req.chat_id, type=req.type,
        user_id=req.user_id, parent_id=req.parent_id,
        metadata=req.metadata,
    )
    return BrainResponse(result={"id": msg_id})

@app.get("/message/by-telegram-id")
def get_by_telegram_message_id(chat_id: int, telegram_message_id: int) -> BrainResponse:
    return BrainResponse(result=db.get_by_telegram_message_id(chat_id, telegram_message_id))

@app.put("/message/{message_id}/metadata")
def update_message_metadata(message_id: str, req: MessageUpdateMetadataRequest) -> BrainResponse:
    db.update_metadata(message_id, req.updates)
    return BrainResponse(result="ok")


class InteractRequest(BaseModel):
    action: str
    payload: dict = {}
    context: dict = {}

@app.post("/interact")
def interact(req: InteractRequest) -> BrainResponse:
    return BrainResponse(result=handle(req.action, req.payload, req.context))


@app.post("/interact/stream")
def interact_stream(req: InteractRequest):
    """SSE endpoint: yields progress events, then the final result."""
    def work(emitter):
        return handle(req.action, req.payload, req.context, progress=emitter)

    return _sse_stream(work)


class EnvSummarizeRequest(BaseModel):
    messages: list[dict]
    environment: str

@app.post("/env/summarize/stream")
def env_summarize_stream(req: EnvSummarizeRequest):
    """SSE endpoint: process chat messages into knowledge entries."""
    summarizer = EnvSummarize(gemini, memory, db, retriever)
    def work(emitter):
        return summarizer.execute(req.messages, req.environment, progress=emitter)
    return _sse_stream(work)


class ScrapeChannelRequest(BaseModel):
    messages: list[dict]
    environment: str


@app.post("/scrape/channel")
def scrape_channel(req: ScrapeChannelRequest) -> BrainResponse:
    """Process fetched channel messages into a daily digest."""
    scraper = ScrapeChannels(gemini, memory, db, retriever)
    result = scraper.process_channel(req.messages, req.environment)
    return BrainResponse(result=result)



@app.get("/scrape/environments")
def list_scrapable_environments() -> BrainResponse:
    """List environments with telegram_handle set (channels to scrape)."""
    return BrainResponse(result=db.list_scrapable_environments())


@app.post("/admin/store-feedback")
def store_feedback(req: StoreFeedbackRequest) -> BrainResponse:
    memory.remember(req.text, domain=req.domain, source="admin_feedback")
    return BrainResponse(result="ok")
