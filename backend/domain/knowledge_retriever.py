from backend.infrastructure.gateways.db_gateway import DbGateway
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

    def __init__(self):
        self._db = DbGateway()
        self._embed = EmbeddingGateway()

    def get_core(self) -> str:
        entries = self._db.get_knowledge_by_tier("core")
        return _format_entries(entries)

    def retrieve(self, query: str, scope: str | None = None, limit: int = 5) -> str:
        embedding = self._embed.embed_one(query)
        entries = self._db.search_knowledge(embedding, scope=scope, limit=limit)
        return _format_entries(entries)

    def retrieve_full_scope(self, scope: str) -> str:
        entries = self._db.get_knowledge_by_scope(scope)
        return _format_entries(entries)
