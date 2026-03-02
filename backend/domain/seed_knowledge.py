"""One-time migration: seed knowledge_entries from .md files."""

import logging
from pathlib import Path

from backend.infrastructure.gateways.db_gateway import DbGateway
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge"


def _read(filename: str) -> str:
    return (KNOWLEDGE_DIR / filename).read_text(encoding="utf-8").strip()


def _chunk_tech_support(text: str) -> list[tuple[str, str, str]]:
    """Split tech-support.md into (tier, title, content) tuples."""
    lines = text.split("\n")
    chunks = []

    # Lines before first "- " bullet are "core" instructions
    core_lines = []
    faq_start = 0
    for i, line in enumerate(lines):
        if line.startswith("- "):
            faq_start = i
            break
        core_lines.append(line)

    if core_lines:
        chunks.append(("core", "Техподдержка: общие правила", "\n".join(core_lines).strip()))

    # Each top-level bullet and its sub-lines
    current_bullet: list[str] = []
    current_title = ""
    for line in lines[faq_start:]:
        if line.startswith("- ") and current_bullet:
            chunks.append(("domain", current_title, "\n".join(current_bullet).strip()))
            current_bullet = [line]
            current_title = line.lstrip("- ").strip()
        elif line.startswith("- "):
            current_bullet = [line]
            current_title = line.lstrip("- ").strip()
        else:
            current_bullet.append(line)

    if current_bullet:
        chunks.append(("domain", current_title, "\n".join(current_bullet).strip()))

    return chunks


def _chunk_payment_validation(text: str) -> list[tuple[str, str]]:
    """Split payment-data-validation.md into (title, content) tuples."""
    chunks = []
    sections = text.split("### ")

    for section in sections:
        section = section.strip()
        if not section:
            continue
        lines = section.split("\n", 1)
        heading = lines[0].strip()

        if "Сбор платёжных данных" in heading:
            chunks.append(("Сбор данных: общие правила", section))
        elif "самозанятый" in heading.lower():
            chunks.append(("Поля: самозанятый", section))
        elif "ИП" in heading:
            chunks.append(("Поля: ИП", section))
        elif "global" in heading.lower():
            chunks.append(("Поля: global", section))
        else:
            chunks.append((heading, section))

    return chunks


def seed_knowledge():
    """Seed knowledge entries from .md files. Safe to re-run (checks existing entries first)."""
    db = DbGateway()
    db.init_schema()
    embed = EmbeddingGateway()

    existing = db.list_knowledge()
    if existing:
        logger.info("Knowledge entries already exist (%d entries), skipping seed", len(existing))
        return

    entries: list[tuple[str, str, str, str]] = []  # (tier, scope, title, content)

    # 1. base.md
    entries.append(("core", "identity", "Republic: базовые правила", _read("base.md")))

    # 2. tech-support.md
    for tier, title, content in _chunk_tech_support(_read("tech-support.md")):
        entries.append((tier, "tech_support", title, content))

    # 3. email-inbox.md
    entries.append(("core", "email_inbox", "Почтовый ящик: классификация", _read("email-inbox.md")))

    # 4. support-triage.md
    entries.append(("domain", "support_triage", "Триаж: определение нужд", _read("support-triage.md")))

    # 5. payment-data-validation.md
    for title, content in _chunk_payment_validation(_read("payment-data-validation.md")):
        entries.append(("domain", "contractor", title, content))

    # 6. claude-code-context.md
    entries.append(("domain", "code", "Контекст для Claude Code", _read("claude-code-context.md")))

    # Generate embeddings in one batch and insert
    logger.info("Seeding %d knowledge entries...", len(entries))
    texts = [e[3] for e in entries]
    embeddings = embed.embed_texts(texts)

    for (tier, scope, title, content), embedding in zip(entries, embeddings):
        entry_id = db.save_knowledge_entry(
            tier=tier, scope=scope, title=title,
            content=content, source="seed", embedding=embedding,
        )
        logger.info("  Saved: [%s] %s / %s (id=%s)", tier, scope, title, entry_id)

    logger.info("Done. %d entries seeded.", len(entries))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_knowledge()
