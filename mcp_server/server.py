"""MCP server exposing MemoryService as tools for Claude."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

_memory = None


def _get_memory():
    global _memory
    if _memory is None:
        from backend.wiring import create_memory_service
        _memory = create_memory_service()
    return _memory


def _resolve_entity(name: str) -> str | None:
    entity = _get_memory().find_entity(query=name)
    return entity["id"] if entity else None


def remember(text: str, domain: str, source: str = "mcp",
             tier: str = "specific", entity_name: str = "",
             source_url: str = "",
             expires_in_days: int = 0) -> dict:
    """Store a fact or piece of information in memory.
    Use expires_in_days to auto-expire the entry after N days."""
    expires_at = None
    if expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    entity_id = _resolve_entity(entity_name) if entity_name else None
    entry_id = _get_memory().remember(
        text, domain, source=source, tier=tier,
        entity_id=entity_id, source_url=source_url or None,
        expires_at=expires_at,
    )
    return {"id": entry_id}


def recall(query: str, domain: str = "", limit: int = 5) -> dict:
    """Search memory for relevant knowledge. Returns a list of matching entries
    ranked by similarity."""
    results = _get_memory().recall(
        query, domain=domain or None, limit=limit,
    )
    return {"results": results}


def teach(text: str) -> dict:
    """Teach the system a new rule or guideline. Domain and tier are
    auto-classified."""
    mem = _get_memory()
    domain, tier = mem.classify_teaching(text)
    entry_id = mem.teach(text, domain=domain, tier=tier)
    return {"id": entry_id, "domain": domain, "tier": tier}


def get_context(environment: str = "", query: str = "") -> dict:
    """Get assembled context for a specific environment."""
    return _get_memory().get_context(
        environment=environment or None, query=query,
    )


def list_domains() -> dict:
    """List all knowledge domains."""
    domains = _get_memory().list_domains()
    return {"domains": domains}


def list_environments() -> dict:
    """List all configured environments."""
    envs = _get_memory().list_environments()
    return {"environments": envs}


def find_entity(query: str) -> dict:
    """Find an entity by name."""
    entity = _get_memory().find_entity(query=query)
    return {"entity": entity}


def add_entity(kind: str, name: str, summary: str = "") -> dict:
    """Add a new entity to the brain. Returns the entity ID."""
    entity_id = _get_memory().add_entity(kind, name, summary=summary)
    return {"id": entity_id}


def entity_note(entity_name: str, text: str, domain: str = "general") -> dict:
    """Store knowledge about a specific entity."""
    entity_id = _resolve_entity(entity_name)
    if not entity_id:
        return {"error": f"Entity '{entity_name}' not found"}
    entry_id = _get_memory().remember(
        text, domain=domain, entity_id=entity_id,
    )
    return {"id": entry_id}


def list_knowledge(domain: str = "", tier: str = "") -> dict:
    """List knowledge entries with optional filters."""
    entries = _get_memory().list_knowledge(
        domain=domain or None, tier=tier or None,
    )
    return {"entries": entries}


# ── MCP registration ─────────────────────────────────────────────

mcp = FastMCP(name="republic-brain")

mcp.tool()(remember)
mcp.tool()(recall)
mcp.tool()(teach)
mcp.tool()(get_context)
mcp.tool()(list_domains)
mcp.tool()(list_environments)
mcp.tool()(find_entity)
mcp.tool()(add_entity)
mcp.tool()(entity_note)
mcp.tool()(list_knowledge)
