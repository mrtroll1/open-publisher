"""MemoryService — unified API layer over the brain's memory."""

from __future__ import annotations

from datetime import datetime

from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.domain.services.knowledge_retriever import KnowledgeRetriever
from backend.domain.services import compose_request

_VALID_TIERS = {"core", "meta", "specific"}


class MemoryService:

    def __init__(self, db: DbGateway | None = None,
                 embed: EmbeddingGateway | None = None,
                 retriever: KnowledgeRetriever | None = None,
                 gemini: GeminiGateway | None = None):
        self._db = db or DbGateway()
        self._embed = embed or EmbeddingGateway()
        self._retriever = retriever or KnowledgeRetriever(self._db, self._embed)
        self._gemini = gemini or GeminiGateway()

    # ── REMEMBER ────────────────────────────────────────────────
    def remember(self, text: str, domain: str, source: str = "api",
                 tier: str = "specific", entity_id: str | None = None,
                 source_url: str | None = None,
                 expires_at: datetime | None = None) -> str:
        embedding = self._embed.embed_one(text)
        existing = self._db.search_knowledge(embedding, domain=domain, limit=1)
        if existing and existing[0].get("similarity", 0) > 0.90:
            entry_id = existing[0]["id"]
            self._db.update_knowledge_entry(entry_id, text, embedding)
            return entry_id
        title = text[:60].strip()
        return self._db.save_knowledge_entry(
            tier=tier, domain=domain, title=title, content=text,
            source=source, embedding=embedding, entity_id=entity_id,
            source_url=source_url, expires_at=expires_at,
        )

    # ── RECALL ─────────────────────────────────────────────────
    def recall(self, query: str, domain: str | None = None,
               domains: list[str] | None = None,
               entity_id: str | None = None,
               limit: int = 5) -> list[dict]:
        embedding = self._embed.embed_one(query)
        if domains is not None:
            entries = self._db.search_knowledge_multi_domain(embedding, domains=domains, limit=limit)
        else:
            entries = self._db.search_knowledge(embedding, domain=domain, limit=limit)
        results = []
        for e in entries:
            results.append({
                "id": e["id"],
                "title": e.get("title", ""),
                "content": e["content"],
                "similarity": e.get("similarity", 0),
                "domain": e.get("domain", ""),
                "tier": e.get("tier", ""),
            })
        return results

    # ── TEACH ──────────────────────────────────────────────────
    def teach(self, text: str, domain: str | None = None,
              tier: str | None = None) -> str:
        if domain is None or tier is None:
            detected_domain, detected_tier = self.classify_teaching(text)
            domain = domain or detected_domain
            tier = tier or detected_tier
        return self._retriever.store_teaching(text, domain=domain, tier=tier)

    # ── CLASSIFY TEACHING ──────────────────────────────────────
    def classify_teaching(self, text: str) -> tuple[str, str]:
        embedding = self._embed.embed_one(text)
        similar = self._db.search_knowledge(embedding, None, 5)
        examples_lines = []
        for e in similar:
            examples_lines.append(f"- [{e['tier']}] {e['domain']} / {e['title']}")
        examples = "\n".join(examples_lines) if examples_lines else ""

        db_domains = self._db.list_domains()
        valid_domain_names = {d["name"] for d in db_domains}
        domains_lines = [f"- **{d['name']}** \u2014 {d['description']}" for d in db_domains]
        domains_text = "\n".join(domains_lines) if domains_lines else "(\u043f\u0443\u0441\u0442\u043e)"

        prompt, model, keys = compose_request.classify_teaching(text, examples, domains_text)
        result = self._gemini.call(prompt, model)
        domain = result.get("domain", "general")
        tier = result.get("tier", "specific")
        if domain not in valid_domain_names:
            domain = "general"
        if tier not in _VALID_TIERS:
            tier = "specific"
        return domain, tier

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

        # Resolve entity context
        user_context = ""
        if user_id:
            entity = self._db.find_entity_by_external_id("telegram_user_id", user_id)
            if entity:
                user_context = self._retriever.get_entity_context(entity["id"])

        return {
            "environment": env_ctx,
            "knowledge": knowledge,
            "user_context": user_context,
            "domains": env_domains or [],
        }

    # ── ENTITY OPS ─────────────────────────────────────────────
    def add_entity(self, kind: str, name: str,
                   external_ids: dict | None = None,
                   summary: str = "") -> str:
        embedding = self._embed.embed_one(name) if name else None
        return self._db.save_entity(kind, name, external_ids=external_ids,
                                    summary=summary, embedding=embedding)

    def find_entity(self, query: str = "", external_key: str = "",
                    external_value: str = "") -> dict | None:
        if external_key and external_value:
            return self._db.find_entity_by_external_id(external_key, external_value)
        if query:
            results = self._db.find_entities_by_name(query, limit=1)
            return results[0] if results else None
        return None

    def update_entity_summary(self, entity_id: str, summary: str) -> bool:
        embedding = self._embed.embed_one(summary) if summary else None
        return self._db.update_entity(entity_id, summary=summary, embedding=embedding)

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
                       entity_id: str | None = None) -> list[dict]:
        if entity_id:
            return self._db.get_entity_knowledge(entity_id)
        return self._db.list_knowledge(domain=domain, tier=tier)

    def get_entry(self, entry_id: str) -> dict | None:
        return self._db.get_knowledge_entry(entry_id)

    def update_entry(self, entry_id: str, content: str) -> bool:
        embedding = self._embed.embed_one(content)
        return self._db.update_knowledge_entry(entry_id, content, embedding)

    def deactivate_entry(self, entry_id: str) -> bool:
        return self._db.deactivate_knowledge(entry_id)
