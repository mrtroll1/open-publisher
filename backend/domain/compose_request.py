"""Compose LLM requests: template + knowledge → (prompt, model, response_keys)."""

from __future__ import annotations

from common.prompt_loader import load_knowledge, load_template

_MODELS = {
    "support_email": "gemini-2.5-flash",
    "support_triage": "gemini-2.5-flash",
    "tech_search_terms": "gemini-2.5-flash",
    "contractor_parse": "gemini-2.5-flash",
    "translate_name": "gemini-2.5-flash",
    "inbox_classify": "gemini-2.5-flash",
    "editorial_assess": "gemini-2.5-flash",
    "tech_support_question": "gemini-2.5-flash",
    "classify_command": "gemini-2.5-flash",
    "conversation_reply": "gemini-2.5-flash",
}

_retriever: KnowledgeRetriever | None = None


def _get_retriever() -> KnowledgeRetriever:
    global _retriever
    if _retriever is None:
        from backend.domain.knowledge_retriever import KnowledgeRetriever
        _retriever = KnowledgeRetriever()
    return _retriever


def support_triage(email_text: str) -> tuple[str, str, list[str]]:
    knowledge = _get_retriever().retrieve_full_scope("support_triage")
    prompt = load_template("support-triage.md", {
        "KNOWLEDGE": knowledge,
        "EMAIL": email_text,
    })
    return prompt, _MODELS["support_triage"], ["needs", "lookup_email"]


def support_email(email_text: str, user_data: str = "") -> tuple[str, str, list[str]]:
    r = _get_retriever()
    knowledge = r.get_core() + "\n\n" + r.retrieve(email_text, "tech_support", 5)
    prompt = load_template("support-email.md", {
        "KNOWLEDGE": knowledge,
        "USER_DATA": user_data,
        "EMAIL": email_text,
    })
    return prompt, _MODELS["support_email"], ["reply"]


def tech_search_terms(text: str) -> tuple[str, str, list[str]]:
    prompt = load_template("tech-search-terms.md", {"EMAIL": text})
    return prompt, _MODELS["tech_search_terms"], ["search_terms", "needs_code"]


def contractor_parse(
    text: str, fields_csv: str, context: str = "",
) -> tuple[str, str, list[str]]:
    r = _get_retriever()
    knowledge = r.get_core() + "\n\n" + r.retrieve_full_scope("contractor")
    prompt = load_template("contractor-parse.md", {
        "FIELDS": fields_csv,
        "CONTEXT": context,
        "INPUT": text,
    })
    if knowledge:
        prompt = knowledge + "\n\n" + prompt
    keys = [f.strip() for f in fields_csv.split(",")]
    return prompt, _MODELS["contractor_parse"], keys


def inbox_classify(email_text: str) -> tuple[str, str, list[str]]:
    prompt = load_template("inbox-classify.md", {"EMAIL": email_text})
    return prompt, _MODELS["inbox_classify"], ["category", "reason"]


def editorial_assess(email_text: str) -> tuple[str, str, list[str]]:
    prompt = load_template("editorial-assess.md", {"EMAIL": email_text})
    return prompt, _MODELS["editorial_assess"], ["forward", "reply"]


def translate_name(name_en: str) -> tuple[str, str, list[str]]:
    prompt = load_template("translate-name.md", {"NAME": name_en})
    return prompt, _MODELS["translate_name"], ["translated_name"]


def tech_support_question(
    question: str, code_context: str = "", verbose: bool = False,
) -> tuple[str, str, list[str]]:
    r = _get_retriever()
    knowledge = r.get_core() + "\n\n" + r.retrieve(question, "tech_support", 5)
    verbose_text = (
        "Можешь дать развёрнутый ответ."
        if verbose
        else "Отвечай кратко, 1-3 абзаца."
    )
    prompt = load_template("tech-support-question.md", {
        "KNOWLEDGE": knowledge,
        "QUESTION": question,
        "CODE_CONTEXT": code_context,
        "VERBOSE": verbose_text,
    })
    return prompt, _MODELS["tech_support_question"], ["answer"]


def classify_command(text: str, commands_description: str) -> tuple[str, str, list[str]]:
    prompt = load_template("classify-command.md", {
        "COMMANDS": commands_description,
        "TEXT": text,
    })
    return prompt, _MODELS["classify_command"], ["command", "args"]


def conversation_reply(
    message: str, conversation_history: str, knowledge_context: str,
    verbose: bool = False,
) -> tuple[str, str, list[str]]:
    verbose_text = (
        "Можешь дать развёрнутый ответ."
        if verbose
        else "Отвечай кратко и по делу."
    )
    prompt = load_template("conversation.md", {
        "VERBOSE": verbose_text,
        "KNOWLEDGE": knowledge_context,
        "CONVERSATION": conversation_history,
        "MESSAGE": message,
    })
    return prompt, _MODELS["conversation_reply"], ["reply"]
