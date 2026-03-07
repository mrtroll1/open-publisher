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
                 expires_at: datetime | None = None) -> str:
        embedding = self._embed.embed_one(text)
        # URL-based dedup: same source_url → update existing entry
        if source_url:
            by_url = self._db.find_by_source_url(source_url)
            if by_url:
                self._db.update_knowledge_entry(by_url["id"], text, embedding)
                return by_url["id"]
        # Embedding-based dedup: very similar content → update
        existing = self._db.search_knowledge(embedding, domain=domain, limit=1)
        if existing and existing[0].get("similarity", 0) > 0.90:
            entry_id = existing[0]["id"]
            self._db.update_knowledge_entry(entry_id, text, embedding)
            return entry_id
        title = text[:60].strip()
        return self._db.save_knowledge_entry(
            tier=tier, domain=domain, title=title, content=text,
            source=source, embedding=embedding, user_id=user_id,
            source_url=source_url, expires_at=expires_at,
        )

    # ── RECALL ─────────────────────────────────────────────────
    def recall(self, query: str, domain: str | None = None,
               domains: list[str] | None = None,
               limit: int = 5) -> list[dict]:
        embedding = self._embed.embed_one(query)
        if domains is not None:
            entries = self._db.search_knowledge_multi_domain(embedding, domains=domains, limit=limit)
        else:
            entries = self._db.search_knowledge(embedding, domain=domain, limit=limit)
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
    def teach(self, text: str, domain: str, tier: str, title: str = "") -> str:
        return self._retriever.store_teaching(text, domain=domain, tier=tier, title=title)

    # ── CONTEXT ────────────────────────────────────────────────
    def get_context(self, environment: str | None = None,
                    chat_id: int | None = None,
                    user_id: int | None = None,
                    query: str = "") -> dict:
        # Resolve environment
        env_ctx = ""
        env_domains: list[str] | None = None
        if environment:
            env = self._db.get_environment(environment)
            if env:
                env_ctx = env.get("system_context", "")
                env_domains = env.get("allowed_domains")
        elif chat_id:
            env = self._db.get_environment_by_chat_id(chat_id)
            if env:
                env_ctx = env.get("system_context", "")
                env_domains = env.get("allowed_domains")

        # Gather knowledge
        if query:
            if env_domains is not None:
                knowledge = self._retriever.get_multi_domain_context(env_domains)
                knowledge += "\n\n" + self._retriever.retrieve(query, domains=env_domains)
            else:
                knowledge = self._retriever.get_core()
                knowledge += "\n\n" + self._retriever.retrieve(query)
        else:
            if env_domains is not None:
                knowledge = self._retriever.get_multi_domain_context(env_domains)
            else:
                knowledge = self._retriever.get_core()

        # Resolve user context
        user_context = ""
        if user_id:
            user = self._db.get_user_by_telegram_id(user_id)
            if user:
                user_context = self._retriever.get_user_context(user["id"])

        return {
            "environment": env_ctx,
            "knowledge": knowledge,
            "user_context": user_context,
            "domains": env_domains or [],
        }

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
