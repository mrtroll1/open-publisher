"""Summarize chat history into knowledge entries for an environment."""

from __future__ import annotations

import logging
from datetime import datetime

from backend.brain.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.memory_service import MemoryService
from backend.infrastructure.repositories.postgres import DbGateway
from backend.models import ProgressEmitter

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50  # messages per LLM call


def _format_messages(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        sender = m.get("sender", "?")
        date = m.get("date", "")
        text = m.get("text", "").strip()
        if text:
            lines.append(f"[{date}] {sender}: {text}")
    return "\n".join(lines)


def _parse_month_range(month: str | None) -> tuple[datetime | None, datetime | None]:
    """Parse 'YYYY-MM' into (start, end) datetimes. None means no filter."""
    if not month:
        return None, None
    try:
        start = datetime.strptime(month, "%Y-%m")
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end
    except ValueError:
        return None, None


class EnvSummarize:
    def __init__(self, gemini: GeminiGateway, memory: MemoryService, db: DbGateway):
        self._gemini = gemini
        self._memory = memory
        self._db = db

    def execute(self, messages: list[dict], environment: str,
                month: str | None = None,
                progress: ProgressEmitter | None = None) -> dict:
        env = self._db.get_environment(environment)
        env_context = env.get("system_context", "") if env else ""
        domains = self._db.list_domains()
        domain_names = ", ".join(d["name"] for d in domains) if domains else "(пусто)"

        filtered = self._filter_by_month(messages, month)
        if not filtered:
            return {"count": 0, "message": "Нет сообщений для обработки."}

        chunks = self._chunk_messages(filtered)
        total_stored = 0

        for i, chunk in enumerate(chunks):
            if progress:
                progress.emit("summarize", f"Обрабатываю блок {i + 1}/{len(chunks)}")

            entries = self._extract_from_chunk(chunk, env_context, domain_names)
            stored = self._store_entries(entries, environment)
            total_stored += stored

        if progress:
            progress.emit("done", f"Извлечено {total_stored} единиц знаний")

        return {"count": total_stored}

    def _filter_by_month(self, messages: list[dict], month: str | None) -> list[dict]:
        if not month:
            return messages
        start, end = _parse_month_range(month)
        if not start:
            return messages
        filtered = []
        for m in messages:
            try:
                date = datetime.fromisoformat(m.get("date", ""))
                if start <= date < end:
                    filtered.append(m)
            except (ValueError, TypeError):
                continue
        return filtered

    def _chunk_messages(self, messages: list[dict]) -> list[list[dict]]:
        return [messages[i:i + CHUNK_SIZE] for i in range(0, len(messages), CHUNK_SIZE)]

    def _extract_from_chunk(self, chunk: list[dict], env_context: str,
                            domain_names: str) -> list[dict]:
        formatted = _format_messages(chunk)
        prompt = load_template("knowledge/extract-chat-knowledge.md", {
            "ENVIRONMENT": env_context or "(не указан)",
            "DOMAINS": domain_names,
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
            title = entry.get("title", "")
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
