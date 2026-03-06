"""Thin async HTTP client wrapping all backend API endpoints."""

import httpx
from common.config import BACKEND_URL

_client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=120.0)


class BackendError(Exception):
    pass


def _unwrap(resp: httpx.Response) -> dict | str | list | None:
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise BackendError(data["error"])
    return data["result"]


# --- Brain ---

async def process(input: str, environment_id: str, user_id: str) -> dict:
    resp = await _client.post("/brain/process", json={
        "input": input, "environment_id": environment_id, "user_id": user_id,
    })
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


# --- Memory ---

async def teach(text: str, domain: str, tier: str = "specific") -> dict:
    resp = await _client.post("/memory/teach", json={
        "text": text, "domain": domain, "tier": tier,
    })
    return _unwrap(resp)


async def memory_search(query: str, domain: str | None = None):
    params = {"query": query}
    if domain:
        params["domain"] = domain
    resp = await _client.get("/memory/search", params=params)
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


# --- Entity ---

async def add_entity(kind: str, name: str, external_ids: dict | None = None,
                     summary: str = "") -> dict:
    resp = await _client.post("/entity/add", json={
        "kind": kind, "name": name,
        "external_ids": external_ids, "summary": summary,
    })
    return _unwrap(resp)


async def find_entity(query: str = "", external_key: str = "",
                      external_value: str = ""):
    params = {}
    if query:
        params["query"] = query
    if external_key:
        params["external_key"] = external_key
    if external_value:
        params["external_value"] = external_value
    resp = await _client.get("/entity/find", params=params)
    return _unwrap(resp)


async def add_entity_note(entity_id: str, text: str, domain: str = "entity_notes"):
    resp = await _client.post(f"/entity/{entity_id}/note", json={
        "text": text, "domain": domain,
    })
    return _unwrap(resp)


async def get_entity_context(user_id: int | str) -> str:
    resp = await _client.get("/entity/context", params={"user_id": str(user_id)})
    return _unwrap(resp) or ""


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
