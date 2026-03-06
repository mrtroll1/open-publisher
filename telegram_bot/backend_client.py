"""Thin async HTTP client wrapping all backend API endpoints."""

import httpx
from common.config import BACKEND_URL

_client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=300.0)


class BackendError(Exception):
    pass


def _unwrap(resp: httpx.Response) -> dict | str | list | None:
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise BackendError(data["error"])
    return data["result"]


# --- Brain ---

async def process(input: str, environment_id: str, user_id: str,
                  chat_id: int | None = None,
                  reply_to_message_id: int | None = None,
                  reply_to_text: str = "") -> dict:
    payload = {
        "input": input, "environment_id": environment_id, "user_id": user_id,
    }
    if chat_id is not None:
        payload["chat_id"] = chat_id
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
        payload["reply_to_text"] = reply_to_text
    resp = await _client.post("/brain/process", json=payload)
    return _unwrap(resp)


async def command(cmd: str, args: str, environment_id: str, user_id: str) -> dict:
    resp = await _client.post("/brain/command", json={
        "command": cmd, "args": args,
        "environment_id": environment_id, "user_id": user_id,
    })
    return _unwrap(resp)


# --- Inbox ---

async def approve_support(uid: str):
    resp = await _client.post("/inbox/approve-support", json={"uid": uid})
    return _unwrap(resp)


async def skip_support(uid: str):
    resp = await _client.post("/inbox/skip-support", json={"uid": uid})
    return _unwrap(resp)


async def approve_editorial(uid: str):
    resp = await _client.post("/inbox/approve-editorial", json={"uid": uid})
    return _unwrap(resp)


async def skip_editorial(uid: str):
    resp = await _client.post("/inbox/skip-editorial", json={"uid": uid})
    return _unwrap(resp)


async def fetch_unread():
    resp = await _client.post("/inbox/fetch-unread")
    return _unwrap(resp)


async def get_pending_support(uid: str) -> dict | None:
    resp = await _client.get(f"/inbox/pending-support/{uid}")
    return _unwrap(resp)


async def get_pending_editorial(uid: str) -> dict | None:
    resp = await _client.get(f"/inbox/pending-editorial/{uid}")
    return _unwrap(resp)


async def update_and_approve_support(uid: str, text: str):
    resp = await _client.post("/inbox/update-and-approve-support", json={
        "uid": uid, "text": text,
    })
    return _unwrap(resp)


# --- Memory ---

async def teach(text: str, domain: str, tier: str = "specific") -> dict:
    resp = await _client.post("/memory/teach", json={
        "text": text, "domain": domain, "tier": tier,
    })
    return _unwrap(resp)


async def classify_teaching(text: str) -> dict:
    resp = await _client.post("/memory/classify-teaching", json={"text": text})
    return _unwrap(resp)


async def memory_search(query: str, domain: str | None = None):
    params = {"query": query}
    if domain:
        params["domain"] = domain
    resp = await _client.get("/memory/search", params=params)
    return _unwrap(resp)


async def memory_list(domain: str | None = None, tier: str | None = None):
    params = {}
    if domain:
        params["domain"] = domain
    if tier:
        params["tier"] = tier
    resp = await _client.get("/memory/list", params=params)
    return _unwrap(resp)


async def get_entry(entry_id: str):
    resp = await _client.get(f"/memory/entry/{entry_id}")
    return _unwrap(resp)


async def update_entry(entry_id: str, content: str):
    resp = await _client.put(f"/memory/entry/{entry_id}", json={"content": content})
    return _unwrap(resp)


async def delete_entry(entry_id: str):
    resp = await _client.delete(f"/memory/entry/{entry_id}")
    return _unwrap(resp)


async def list_domains():
    resp = await _client.get("/memory/domains")
    return _unwrap(resp)


async def list_environments():
    resp = await _client.get("/memory/environments")
    return _unwrap(resp)


async def get_environment(chat_id: int = 0, name: str = "") -> dict | None:
    params = {}
    if chat_id:
        params["chat_id"] = chat_id
    if name:
        params["name"] = name
    resp = await _client.get("/memory/environment", params=params)
    return _unwrap(resp)


async def create_environment(name: str, description: str, system_context: str = ""):
    resp = await _client.post("/memory/environment/create", json={
        "name": name, "description": description, "system_context": system_context,
    })
    return _unwrap(resp)


async def update_environment(name: str, **kwargs):
    payload = {"name": name, **kwargs}
    resp = await _client.put("/memory/environment/update", json=payload)
    return _unwrap(resp)


async def bind_environment(chat_id: int, name: str):
    resp = await _client.post("/memory/environment/bind", json={
        "chat_id": chat_id, "name": name,
    })
    return _unwrap(resp)


async def unbind_environment(chat_id: int):
    resp = await _client.post("/memory/environment/unbind", params={"chat_id": chat_id})
    return _unwrap(resp)


async def get_bindings(name: str) -> list:
    resp = await _client.get("/memory/environment/bindings", params={"name": name})
    return _unwrap(resp)


# --- User ---

async def get_admin_telegram_ids() -> list[int]:
    resp = await _client.get("/user/admin_telegram_ids")
    return _unwrap(resp) or []


async def is_admin(telegram_id: int) -> bool:
    resp = await _client.get("/user/is_admin", params={"telegram_id": telegram_id})
    return _unwrap(resp) or False


async def get_user_context(telegram_id: int | str) -> str:
    resp = await _client.get("/user/context", params={"telegram_id": int(telegram_id)})
    return _unwrap(resp) or ""


async def add_user_note(user_id: str, text: str, domain: str = "general"):
    resp = await _client.post(f"/user/{user_id}/note", json={
        "text": text, "domain": domain,
    })
    return _unwrap(resp)


# --- Conversation ---

async def save_turn(chat_id: int, user_id: int, role: str, content: str,
                    reply_to_id: str | None = None, message_id: int | None = None,
                    metadata: dict | None = None) -> str:
    resp = await _client.post("/conversation/save", json={
        "chat_id": chat_id, "user_id": user_id,
        "role": role, "content": content,
        "reply_to_id": reply_to_id, "message_id": message_id,
        "metadata": metadata,
    })
    result = _unwrap(resp)
    return result["id"]


async def get_conversation_by_message_id(chat_id: int, message_id: int) -> dict | None:
    resp = await _client.get("/conversation/by-message-id", params={
        "chat_id": chat_id, "message_id": message_id,
    })
    return _unwrap(resp)


# --- Classification / code tasks ---

async def log_classification(task: str, model: str, prompt: str,
                             result: str, latency_ms: int):
    resp = await _client.post("/classification/log", json={
        "task": task, "model": model, "prompt": prompt,
        "result": result, "latency_ms": latency_ms,
    })
    return _unwrap(resp)


async def create_code_task(requested_by: str, input_text: str,
                           output_text: str, verbose: bool = False) -> str:
    resp = await _client.post("/code-task/create", json={
        "requested_by": requested_by, "input_text": input_text,
        "output_text": output_text, "verbose": verbose,
    })
    return _unwrap(resp)["id"]


async def rate_code_task(task_id: str, rating: int):
    resp = await _client.post("/code-task/rate", json={
        "task_id": task_id, "rating": rating,
    })
    return _unwrap(resp)


async def finalize_payment_validation(validation_id: str):
    resp = await _client.post("/payment/finalize-validation", json={
        "validation_id": validation_id,
    })
    return _unwrap(resp)


async def store_feedback(text: str, domain: str):
    resp = await _client.post("/admin/store-feedback", json={
        "text": text, "domain": domain,
    })
    return _unwrap(resp)
