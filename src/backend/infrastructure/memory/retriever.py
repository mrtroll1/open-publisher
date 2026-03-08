from backend.config import SUBSCRIPTION_SERVICE_URL
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
from backend.infrastructure.repositories.postgres import DbGateway


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

    def get_context(self, *, role: str = "admin", user_id: str | None = None,
                    environment: str | None = None) -> str:
        """Core (always public) + meta entries visible to caller."""
        core = self._db.get_knowledge_by_tier("core")
        meta = self._db.get_visible_meta(role=role, user_id=user_id, environment=environment)
        return _format_entries(core + meta)

    def get_domain_context(self, domain: str) -> str:
        """Core (global) + meta (domain-wide) knowledge. For internal pipelines."""
        entries = self._db.get_domain_context(domain)
        return _format_entries(entries)

    def retrieve(self, query: str, *, role: str = "admin", user_id: str | None = None,
                 environment: str | None = None, domain: str | None = None,
                 limit: int = 5, min_similarity: float = 0.6) -> str:
        embedding = self._embed.embed_one(query)
        entries = self._db.search_knowledge(
            embedding, role=role, user_id=user_id, environment=environment,
            domain=domain, limit=limit,
        )
        entries = [e for e in entries if e.get("similarity", 0) >= min_similarity]
        return _format_entries(entries)

    def retrieve_full_domain(self, domain: str) -> str:
        entries = self._db.get_knowledge_by_domain(domain)
        return _format_entries(entries)

    def _dedup_or_create(self, text: str, domain: str, source: str, *,  # noqa: PLR0913
                         tier: str = "specific", title: str = "",
                         user_id: str | None = None,
                         skip_dedup: bool = False,
                         visibility: str = "public",
                         environment_id: str | None = None,
                         source_type: str = "") -> str:
        embedding = self._embed.embed_one(text)
        if not skip_dedup:
            # Dedup uses admin role to find any existing match
            existing = self._db.search_knowledge(embedding, domain=domain, limit=1)
            if existing and existing[0].get("similarity", 0) > 0.90:
                self._db.update_knowledge_entry(existing[0]["id"], text, embedding)
                return existing[0]["id"]
        return self._db.save_knowledge_entry(
            tier=tier, domain=domain, title=title or text[:60].strip(),
            content=text, source=source, embedding=embedding, user_id=user_id,
            visibility=visibility, environment_id=environment_id, source_type=source_type,
        )

    def store_feedback(self, text: str, domain: str) -> str:
        return self._dedup_or_create(text, domain, "admin_feedback")

    def store_user_knowledge(self, user_id: str, text: str, domain: str = "general") -> str:
        return self._dedup_or_create(text, domain, "admin_teach",
                                     user_id=user_id, visibility="user")

    def store_teaching(self, text: str, domain: str = "general", tier: str = "specific",
                       title: str = "", visibility: str = "public") -> str:
        skip_dedup = tier != "specific"
        return self._dedup_or_create(text, domain, "admin_teach", tier=tier, title=title,
                                     skip_dedup=skip_dedup, visibility=visibility)

    def get_user_context(self, user_id: str) -> str:
        user = self._db.get_user(user_id)
        if not user:
            return ""
        entries = self._db.get_user_knowledge(user_id, limit=5)
        if not entries:
            return ""
        parts = []
        if user.get("name"):
            parts.append(f"## {user['name']}")
        parts.append(_format_entries(entries))
        return "\n\n".join(parts)
