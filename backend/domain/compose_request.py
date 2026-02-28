"""Compose LLM requests: template + knowledge → (prompt, model, response_keys)."""

from common.config import SUBSCRIPTION_SERVICE_URL
from common.prompt_loader import load_knowledge, load_template

_MODELS = {
    "support_email": "gemini-2.5-flash",
    "support_triage": "gemini-2.5-flash",
    "contractor_parse": "gemini-2.5-flash",
    "translate_name": "gemini-2.5-flash",
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


def translate_name(name_en: str) -> tuple[str, str, list[str]]:
    prompt = load_template("translate-name.md", {"NAME": name_en})
    return prompt, _MODELS["translate_name"], ["translated_name"]
