"""Conversation business logic — context building and NL reply generation."""

from __future__ import annotations

from backend.domain.services import compose_request
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.domain.services.knowledge_retriever import KnowledgeRetriever


def format_reply_chain(chain: list[dict]) -> str:
    parts = []
    for entry in chain:
        role = entry["role"]
        content = entry["content"]
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def build_conversation_context(
    chat_id: int,
    reply_message_id: int,
    reply_text: str,
    db: DbGateway,
) -> tuple[str, str | None]:
    """Look up conversation chain from DB; bootstrap from reply text if not found.

    Returns (history_str, parent_id).
    """
    conv_entry = db.get_conversation_by_message_id(chat_id, reply_message_id)

    if conv_entry:
        chain = db.get_reply_chain(conv_entry["id"], depth=10)
        history = format_reply_chain(chain)
        return history, conv_entry["id"]

    history = f"assistant: {reply_text}"
    return history, None


def generate_nl_reply(
    message_text: str,
    conversation_history: str,
    retriever: KnowledgeRetriever,
    gemini: GeminiGateway | None = None,
    verbose: bool = False,
    environment: str = "",
    allowed_domains: list[str] | None = None,
) -> str:
    """Build knowledge context, call LLM, return reply text."""
    if allowed_domains is not None:
        core = retriever.get_multi_domain_context(allowed_domains)
        relevant = retriever.retrieve(message_text, domains=allowed_domains)
    else:
        core = retriever.get_core()
        relevant = retriever.retrieve(message_text)
    knowledge_context = core + "\n\n" + relevant if core else relevant

    prompt, model, _ = compose_request.conversation_reply(
        message_text, conversation_history, knowledge_context,
        verbose=verbose, environment_context=environment,
    )

    if gemini is None:
        gemini = GeminiGateway()
    result = gemini.call(prompt, model)
    answer = result.get("reply", str(result))

    if len(answer) > 4000:
        answer = answer[:4000]

    return answer
