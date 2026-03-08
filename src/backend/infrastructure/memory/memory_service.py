"""MemoryService — unified API layer over the brain's memory."""

from __future__ import annotations

from datetime import datetime

from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.repositories.postgres import DbGateway


class MemoryService:

    def __init__(self, db: DbGateway | None = None,
                 embed: EmbeddingGateway | None = None,
                 retriever: KnowledgeRetriever | None = None):
        self._db = db or DbGateway()
        self._embed = embed or EmbeddingGateway()
        self._retriever = retriever or KnowledgeRetriever(self._db, self._embed)

    # ── REMEMBER ────────────────────────────────────────────────
    def remember(self, text: str, domain: str, *, source: str = "api",  # noqa: PLR0913
                 tier: str = "specific", user_id: str | None = None,
                 source_url: str | None = None,
                 expires_at: datetime | None = None,
                 visibility: str = "public",
                 environment_id: str | None = None,
                 source_type: str = "") -> str:
        embedding = self._embed.embed_one(text)
        existing_id = self._find_duplicate(embedding, domain, source_url)
        if existing_id:
            self._db.update_knowledge_entry(existing_id, text, embedding)
            return existing_id
        return self._db.save_knowledge_entry(
            tier=tier, domain=domain, title=text[:60].strip(), content=text,
            source=source, embedding=embedding, user_id=user_id,
            source_url=source_url, expires_at=expires_at,
            visibility=visibility, environment_id=environment_id,
            source_type=source_type,
        )

    def _find_duplicate(self, embedding, domain: str, source_url: str | None) -> str | None:
        if source_url:
            by_url = self._db.find_by_source_url(source_url)
            if by_url:
                return by_url["id"]
        existing = self._db.search_knowledge(embedding, domain=domain, limit=1)
        if existing and existing[0].get("similarity", 0) > 0.90:
            return existing[0]["id"]
        return None

    # ── RECALL ─────────────────────────────────────────────────
    def recall(self, query: str, *, role: str = "admin", user_id: str | None = None,
               environment: str | None = None, domain: str | None = None,
               limit: int = 5) -> list[dict]:
        embedding = self._embed.embed_one(query)
        entries = self._db.search_knowledge(
            embedding, role=role, user_id=user_id, environment=environment,
            domain=domain, limit=limit,
        )
        return [
            {
                "id": e["id"],
                "title": e.get("title", ""),
                "content": e["content"],
                "similarity": e.get("similarity", 0),
                "domain": e.get("domain", ""),
                "tier": e.get("tier", ""),
            }
            for e in entries
        ]

    # ── TEACH ──────────────────────────────────────────────────
    def teach(self, text: str, domain: str, tier: str, title: str = "",
              visibility: str = "public") -> str:
        return self._retriever.store_teaching(text, domain=domain, tier=tier, title=title,
                                              visibility=visibility)

    # ── CONTEXT ────────────────────────────────────────────────
    def get_context(self, *, environment: str | None = None,
                    chat_id: int | None = None,
                    user_id: int | None = None,
                    role: str = "admin",
                    query: str = "") -> dict:
        env = self._resolve_env(environment, chat_id)
        env_ctx = env.get("system_context", "") if env else ""
        env_name = env.get("name") if env else None
        user_id_str = self._resolve_user_id(user_id)
        knowledge = self._gather_knowledge(role=role, user_id=user_id_str,
                                           environment=env_name, query=query)
        user_context = self._retriever.get_user_context(user_id_str) if user_id_str else ""
        return {
            "environment": env_ctx,
            "knowledge": knowledge,
            "user_context": user_context,
        }

    def _resolve_env(self, environment: str | None, chat_id: int | None) -> dict | None:
        if environment:
            return self._db.get_environment(environment)
        if chat_id:
            return self._db.get_environment_by_chat_id(chat_id)
        return None

    def _resolve_user_id(self, telegram_id: int | None) -> str | None:
        if not telegram_id:
            return None
        user = self._db.get_user_by_telegram_id(telegram_id)
        return user["id"] if user else None

    def _gather_knowledge(self, *, role: str, user_id: str | None,
                          environment: str | None, query: str) -> str:
        base = self._retriever.get_context(role=role, user_id=user_id, environment=environment)
        if not query:
            return base
        relevant = self._retriever.retrieve(
            query, role=role, user_id=user_id, environment=environment,
        )
        return base + "\n\n" + relevant if base else relevant

    # ── USER OPS ───────────────────────────────────────────────
    def get_user(self, user_id: str) -> dict | None:
        return self._db.get_user(user_id)

    def get_user_by_telegram_id(self, telegram_id: int) -> dict | None:
        return self._db.get_user_by_telegram_id(telegram_id)

    # ── ENVIRONMENT OPS ────────────────────────────────────────
    def list_environments(self) -> list[dict]:
        return self._db.list_environments()

    def get_environment(self, name: str = "", chat_id: int = 0) -> dict | None:
        if chat_id:
            return self._db.get_environment_by_chat_id(chat_id)
        if name:
            return self._db.get_environment(name)
        return None

    def update_environment(self, name: str, **fields) -> bool:
        return self._db.update_environment(name, **fields)

    # ── DOMAIN OPS ─────────────────────────────────────────────
    def list_domains(self) -> list[dict]:
        return self._db.list_domains()

    def add_domain(self, name: str, description: str = "") -> str:
        return self._db.get_or_create_domain(name, description)

    # ── KNOWLEDGE MANAGEMENT ───────────────────────────────────
    def list_knowledge(self, domain: str | None = None,
                       tier: str | None = None,
                       user_id: str | None = None) -> list[dict]:
        if user_id:
            return self._db.get_user_knowledge(user_id)
        return self._db.list_knowledge(domain=domain, tier=tier)

    def get_entry(self, entry_id: str) -> dict | None:
        return self._db.get_knowledge_entry(entry_id)

    def update_entry(self, entry_id: str, content: str) -> bool:
        embedding = self._embed.embed_one(content)
        return self._db.update_knowledge_entry(entry_id, content, embedding)

    def deactivate_entry(self, entry_id: str) -> bool:
        return self._db.deactivate_knowledge(entry_id)
