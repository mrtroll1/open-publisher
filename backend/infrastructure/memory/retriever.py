from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
from common.config import SUBSCRIPTION_SERVICE_URL


def _format_entries(entries: list[dict]) -> str:
    parts = []
    for e in entries:
        title = e.get("title", "")
        content = e["content"]
        if title:
            parts.append(f"## {title}\n{content}")
        else:
            parts.append(content)
    result = "\n\n".join(parts)
    return result.replace("{{SUBSCRIPTION_SERVICE_URL}}", SUBSCRIPTION_SERVICE_URL)


class KnowledgeRetriever:

    def __init__(self, db: DbGateway | None = None, embed: EmbeddingGateway | None = None):
        self._db = db or DbGateway()
        self._embed = embed or EmbeddingGateway()

    def get_core(self) -> str:
        entries = self._db.get_knowledge_by_tier("core")
        return _format_entries(entries)

    def get_domain_context(self, domain: str) -> str:
        """Core (global) + meta (domain-wide) knowledge."""
        entries = self._db.get_domain_context(domain)
        return _format_entries(entries)

    def get_multi_domain_context(self, domains: list[str]) -> str:
        """Core (global) + meta entries for multiple domains."""
        entries = self._db.get_multi_domain_context(domains)
        return _format_entries(entries)

    def retrieve(self, query: str, domain: str | None = None, domains: list[str] | None = None,
                 limit: int = 5, min_similarity: float = 0.6) -> str:
        embedding = self._embed.embed_one(query)
        if domains is not None:
            entries = self._db.search_knowledge_multi_domain(embedding, domains=domains, limit=limit)
        else:
            entries = self._db.search_knowledge(embedding, domain=domain, limit=limit)
        entries = [e for e in entries if e.get("similarity", 0) >= min_similarity]
        return _format_entries(entries)

    def retrieve_full_domain(self, domain: str) -> str:
        entries = self._db.get_knowledge_by_domain(domain)
        return _format_entries(entries)

    def store_feedback(self, text: str, domain: str) -> str:
        embedding = self._embed.embed_one(text)
        existing = self._db.search_knowledge(embedding, domain=domain, limit=1)
        if existing and existing[0].get("similarity", 0) > 0.90:
            entry_id = existing[0]["id"]
            self._db.update_knowledge_entry(entry_id, text, embedding)
            return entry_id
        title = text[:60].strip()
        return self._db.save_knowledge_entry(
            tier="specific",
            domain=domain,
            title=title,
            content=text,
            source="admin_feedback",
            embedding=embedding,
        )

    def get_user_context(self, user_id: str) -> str:
        """Fetch user-linked knowledge entries. Format as markdown."""
        user = self._db.get_user(user_id)
        if not user:
            return ""
        parts = []
        entries = self._db.get_user_knowledge(user_id, limit=5)
        if entries:
            if user.get("name"):
                parts.append(f"## {user['name']}")
            parts.append(_format_entries(entries))
        return "\n\n".join(parts)

    def store_user_knowledge(self, user_id: str, text: str,
                              domain: str = "general") -> str:
        """Store a knowledge entry linked to a user. Dedup-aware."""
        embedding = self._embed.embed_one(text)
        existing = self._db.search_knowledge(embedding, domain=domain, limit=1)
        if existing and existing[0].get("similarity", 0) > 0.90:
            entry_id = existing[0]["id"]
            self._db.update_knowledge_entry(entry_id, text, embedding)
            return entry_id
        title = text[:60].strip()
        return self._db.save_knowledge_entry(
            tier="specific", domain=domain, title=title,
            content=text, source="admin_teach",
            embedding=embedding, user_id=user_id,
        )

    def store_teaching(self, text: str, domain: str = "general", tier: str = "specific") -> str:
        embedding = self._embed.embed_one(text)
        # Only dedup specific-tier entries; core/meta are intentionally distinct
        if tier == "specific":
            existing = self._db.search_knowledge(embedding, domain=domain, limit=1)
            if existing and existing[0].get("similarity", 0) > 0.90:
                entry_id = existing[0]["id"]
                self._db.update_knowledge_entry(entry_id, text, embedding)
                return entry_id
        title = text[:60].strip()
        return self._db.save_knowledge_entry(
            tier=tier,
            domain=domain,
            title=title,
            content=text,
            source="admin_teach",
            embedding=embedding,
        )
