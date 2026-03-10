"""Summarize chat history into knowledge entries for an environment."""

from __future__ import annotations

import logging
from datetime import datetime

from backend.brain.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.memory_service import MemoryService
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.repositories.postgres import DbGateway
from backend.models import ProgressEmitter

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50  # messages per LLM call


def _format_messages(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        sender = m.get("sender", "?")
        sender_id = m.get("sender_id", "")
        date = m.get("date", "")
        text = m.get("text", "").strip()
        if text:
            tag = f"{sender} (tg_id={sender_id})" if sender_id else sender
            lines.append(f"[{date}] {tag}: {text}")
    return "\n".join(lines)


class EnvSummarize:
    def __init__(self, gemini: GeminiGateway, memory: MemoryService, db: DbGateway,
                 retriever: KnowledgeRetriever | None = None):
        self._gemini = gemini
        self._memory = memory
        self._db = db
        self._retriever = retriever

    def execute(self, messages: list[dict], environment: str,
                progress: ProgressEmitter | None = None) -> dict:
        env = self._db.get_environment(environment)
        env_context = env.get("system_context", "") if env else ""
        domains = self._db.list_domains()
        domain_names = ", ".join(d["name"] for d in domains) if domains else "(пусто)"
        users = self._db.list_users()
        users_info = self._format_users(users)
        knowledge = self._retriever.get_core() if self._retriever else ""

        if not messages:
            return {"count": 0, "message": "Нет сообщений для обработки."}

        chunks = self._chunk_messages(messages)
        total_stored = 0

        for i, chunk in enumerate(chunks):
            if progress:
                progress.emit("summarize", f"Обрабатываю блок {i + 1}/{len(chunks)}")

            entries = self._extract_from_chunk(chunk, env_context, domain_names, users_info, knowledge)
            stored = self._store_entries(entries, environment)
            total_stored += stored

        self._db.update_environment(environment, last_summarized_at=datetime.utcnow())

        if progress:
            progress.emit("done", f"Извлечено {total_stored} единиц знаний")

        return {"count": total_stored}

    def _chunk_messages(self, messages: list[dict]) -> list[list[dict]]:
        return [messages[i:i + CHUNK_SIZE] for i in range(0, len(messages), CHUNK_SIZE)]

    @staticmethod
    def _format_users(users: list[dict]) -> str:
        if not users:
            return "(нет зарегистрированных пользователей)"
        lines = []
        for u in users:
            parts = [u.get("name") or "?", f"role={u.get('role', '?')}"]
            if u.get("telegram_id"):
                parts.append(f"tg_id={u['telegram_id']}")
            if u.get("email"):
                parts.append(u["email"])
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    def _extract_from_chunk(self, chunk: list[dict], env_context: str,
                            domain_names: str, users_info: str,
                            knowledge: str = "") -> list[dict]:
        formatted = _format_messages(chunk)
        prompt = load_template("knowledge/extract-chat-knowledge.md", {
            "KNOWLEDGE": knowledge or "(нет)",
            "ENVIRONMENT": env_context or "(не указан)",
            "DOMAINS": domain_names,
            "USERS": users_info,
            "MESSAGES": formatted,
        })
        try:
            result = self._gemini.call(prompt)
            return result.get("entries", [])
        except Exception:
            logger.exception("Failed to extract knowledge from chat chunk")
            return []

    def _store_entries(self, entries: list[dict], environment: str) -> int:
        stored = 0
        for entry in entries:
            domain = entry.get("domain", "general")
            tier = entry.get("tier", "specific")
            visibility = entry.get("visibility", "environment")
            content = entry.get("content", "")
            if not content:
                continue
            self._db.get_or_create_domain(domain)
            self._memory.remember(
                content, domain,
                source="chat_summary", tier=tier,
                visibility=visibility, environment_id=environment,
                source_type="chat_summary",
            )
            stored += 1
        return stored
