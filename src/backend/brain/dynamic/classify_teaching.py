from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.repositories.postgres import DbGateway


class ClassifyTeaching(BaseGenAI):

    def __init__(self, gemini: GeminiGateway, db: DbGateway, embed: EmbeddingGateway):
        super().__init__(gemini)
        self._db = db
        self._embed = embed

    def _pick_template(self, _input: str, _context: dict) -> str:
        return "knowledge/classify-teaching.md"

    def _build_context(self, input: str, _context: dict) -> dict:
        embedding = self._embed.embed_one(input)
        similar = self._db.search_knowledge(embedding, limit=5)
        examples = "\n".join(e["content"][:200] for e in similar) if similar else "(пусто)"

        domains = self._db.list_domains()
        domain_names = ", ".join(d["name"] for d in domains) if domains else "(пусто)"

        return {
            "TEXT": input,
            "EXAMPLES": examples,
            "DOMAINS": domain_names,
        }

    def _parse_response(self, raw: dict) -> dict:
        domain = raw.get("domain", "general")
        tier = raw.get("tier", "specific")
        visibility = raw.get("visibility", "public")
        self._db.get_or_create_domain(domain)
        return {"domain": domain, "tier": tier, "visibility": visibility}
