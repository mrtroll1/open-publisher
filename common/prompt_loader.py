"""Load LLM prompt templates and knowledge files from disk."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES = _ROOT / "templates"
_KNOWLEDGE = _ROOT / "knowledge"


def load_template(name: str, replacements: dict[str, str] | None = None) -> str:
    text = (_TEMPLATES / name).read_text(encoding="utf-8")
    for key, val in (replacements or {}).items():
        text = text.replace(f"{{{{{key}}}}}", val)
    return text


def load_knowledge(
    *filenames: str, replacements: dict[str, str] | None = None,
) -> str:
    parts = []
    for name in filenames:
        path = _KNOWLEDGE / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    text = "\n\n---\n\n".join(parts)
    for key, val in (replacements or {}).items():
        text = text.replace(f"{{{{{key}}}}}", val)
    return text
