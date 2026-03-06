"""Load LLM prompt templates from disk."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES = _ROOT / "templates"


def load_template(name: str, replacements: dict[str, str] | None = None) -> str:
    text = (_TEMPLATES / name).read_text(encoding="utf-8")
    for key, val in (replacements or {}).items():
        text = text.replace(f"{{{{{key}}}}}", val)
    return text
