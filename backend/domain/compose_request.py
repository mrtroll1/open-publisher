"""Compose LLM requests: template + knowledge → (prompt, model, response_keys)."""

from common.config import SUBSCRIPTION_SERVICE_URL
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
}


def support_triage(email_text: str) -> tuple[str, str, list[str]]:
    knowledge = load_knowledge(
        "support-triage.md",
        replacements={"SUBSCRIPTION_SERVICE_URL": SUBSCRIPTION_SERVICE_URL},
    )
    prompt = load_template("support-triage.md", {
        "KNOWLEDGE": knowledge,
        "EMAIL": email_text,
    })
    return prompt, _MODELS["support_triage"], ["needs", "lookup_email"]


def support_email(email_text: str) -> tuple[str, str, list[str]]:
    knowledge = load_knowledge(
        "base.md", "email-inbox.md", "tech-support.md",
        replacements={"SUBSCRIPTION_SERVICE_URL": SUBSCRIPTION_SERVICE_URL},
    )
    prompt = load_template("support-email.md", {
        "KNOWLEDGE": knowledge,
        "USER_DATA": "",
        "EMAIL": email_text,
    })
    return prompt, _MODELS["support_email"], ["reply"]


def support_email_with_context(email_text: str, user_data: str) -> tuple[str, str, list[str]]:
    knowledge = load_knowledge(
        "base.md", "email-inbox.md", "tech-support.md",
        replacements={"SUBSCRIPTION_SERVICE_URL": SUBSCRIPTION_SERVICE_URL},
    )
    prompt = load_template("support-email.md", {
        "KNOWLEDGE": knowledge,
        "USER_DATA": user_data,
        "EMAIL": email_text,
    })
    return prompt, _MODELS["support_email"], ["reply"]


def tech_search_terms(email_text: str) -> tuple[str, str, list[str]]:
    prompt = load_template("tech-search-terms.md", {"EMAIL": email_text})
    return prompt, _MODELS["tech_search_terms"], ["search_terms", "needs_code"]


def contractor_parse(
    text: str, fields_csv: str, context: str = "",
) -> tuple[str, str, list[str]]:
    knowledge = load_knowledge("base.md", "payment-data-validation.md")
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
    knowledge = load_knowledge(
        "base.md", "tech-support.md",
        replacements={"SUBSCRIPTION_SERVICE_URL": SUBSCRIPTION_SERVICE_URL},
    )
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
